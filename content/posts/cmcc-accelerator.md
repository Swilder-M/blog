---
title: "某软件教育加速协议分析和使用"
date: 2025-08-27T20:00:00+08:00
tags: ["网络协议", "SOCKS5", "代理", "逆向工程"]
keywords: ["SOCKS5", "代理协议", "网络加速", "协议分析", "CMCC", "教育加速", "逆向分析", "Docker"]
description: "本文深度分析某教育加速软件基于 SOCKS5 协议的私有实现，详细解析 XOR 0xFF 数据混淆机制以及 0x80 和 0x82 两种私有认证方式的数据包结构。包含完整的协议逆向过程、配置信息提取方法、Docker 部署方案，以及实际使用场景分享。适合网络协议研究和代理技术学习。"
draft: false
---

前段时间注意到某 APP 有一个教育加速功能，经过测试，这个功能其实使用了一个类似 SOCKS5 的代理协议，将白名单内的流量（一些海外大学网站）通过代理服务器转发，从而实现加速效果。

这个代理协议其实是基于 SOCKS5 进行了少量修改，为了更好地理解这些修改，先简单介绍一下 SOCKS5 的协议结构。

## SOCKS5 协议的工作流程

SOCKS5 协议建立连接的过程分为三个主要阶段：认证协商、身份验证和连接请求。下面是完整的工作流程：

```
Client                     SOCKS5 Proxy                Target Server
  |                              |                           |
  |  -- Auth Method Request -->  |                           |
  |  <-- Auth Method Response -  |                           |
  |                              |                           |
  |  -- Authentication Req -->   |                           |
  |  <-- Authentication Resp -   |                           |
  |                              |                           |
  |  -- Connection Request -->   |  --- TCP Connection --->  |
  |  <-- Connection Response -   |  <-- TCP Connection ACK - |
  |                              |                           |
  |  <----- Data Relay ------>   |  <----- Data Relay ---->  |
```

### 1. 认证协商阶段

客户端首先向 SOCKS5 代理发送认证方法协商请求：

```
认证协商请求包结构：
+-----+----------+----------+
| VER | NMETHODS | METHODS  |
+-----+----------+----------+
|  1  |    1     | 1 to 255 |
+-----+----------+----------+

VER: 版本号 (0x05 for SOCKS5)
NMETHODS: 支持的认证方法数量
METHODS: 支持的认证方法列表
  - 0x00: 无需认证
  - 0x01: GSSAPI
  - 0x02: 用户名/密码认证
  - 0x03-0x7F: IANA 分配
  - 0x80-0xFE: 私有方法
  - 0xFF: 无可接受方法
```

代理服务器响应选择的认证方法：

```
认证协商响应包结构：
+-----+--------+
| VER | METHOD |
+-----+--------+
|  1  |   1    |
+-----+--------+

VER: 版本号 (0x05)
METHOD: 选择的认证方法
```

### 2. 身份验证阶段

如果选择了用户名/密码认证（`0x02`），客户端需要发送认证信息：

```
用户名/密码认证请求：
+-----+------+----------+------+----------+
| VER | ULEN |  UNAME   | PLEN |  PASSWD  |
+-----+------+----------+------+----------+
|  1  |  1   | 1 to 255 |  1   | 1 to 255 |
+-----+------+----------+------+----------+

VER: 子协议版本号 (0x01)
ULEN: 用户名长度
UNAME: 用户名
PLEN: 密码长度
PASSWD: 密码
```

代理服务器返回认证结果：

```
用户名/密码认证响应：
+-----+--------+
| VER | STATUS |
+-----+--------+
|  1  |   1    |
+-----+--------+

VER: 子协议版本号 (0x01)
STATUS: 认证状态 (0x00 成功，其他失败)
```

### 3. 连接请求和数据传输阶段

这两个阶段的流程和数据包格式较为复杂，且与后续分析的加速器协议差异不大，这里不再详述。如需了解完整的 SOCKS5 协议规范，请参考 [RFC 1928](https://datatracker.ietf.org/doc/html/rfc1928)。

## 某加速器的协议

了解了标准 SOCKS5 协议后，我们来看看这个教育加速器的协议有何不同：

### 1. 数据混淆处理
所有客户端发送的数据包都要 XOR `0xFF` 进行混淆处理，而服务器返回的数据包不需要处理，这是该加速器协议与标准 SOCKS5 最显著的区别。

例如，客户端发送认证方法协商请求：
- 原始数据：`05 01 80`（SOCKS5 版本，1 种方法，方法 `0x80`）
- 发送数据：`FA FE 7F`（每个字节与 `0xFF` 按位异或）

### 2. 私有认证方式
此加速器支持两种私有认证方式：
- 0x80
- 0x82

#### Type 0x80 认证请求包结构:
```
+-----+------+----------+------+----------+
| VER | ULEN |  UNAME   | HLEN |   HMAC   |
+-----+------+----------+------+----------+
|  1  |  1   |    19    |  1   |    32    |
+-----+------+----------+------+----------+

VER: 子协议版本号 (0x01)
ULEN: 用户名长度 (19)
UNAME: 用户名 (19 字节)
HLEN: HMAC 长度 (0x20 = 32)
HMAC: HMAC-SHA256 签名 (32 字节)
```

HMAC 计算方式：
- 密钥：USERNAME + PASSWORD
- 消息：单字节质询值（服务器在方法协商响应的第二字节返回）
- 算法：HMAC-SHA256

握手过程：
1. 客户端发送：`0x05 0x01 0x80`（XOR 后：`0xFA 0xFE 0x7F`）
2. 服务器响应：`0x05 [质询字节]`
3. 客户端发送认证包（54 字节，XOR 混淆）
4. 服务器响应：`0x01 0x00`（成功）或其他（失败）


#### Type 0x82 认证请求包结构:
```
+-----+------+----------+------+----------+----------+
| VER | ULEN |  UNAME   | HLEN |   HMAC   | FIXDATA  |
+-----+------+----------+------+----------+----------+
|  1  |  1   |    19    |  1   |    32    |    21    |
+-----+------+----------+------+----------+----------+

VER: 子协议版本号 (0x01)
ULEN: 用户名长度 (19)
UNAME: 用户名 (19 字节)
HLEN: HMAC 长度 (0x20 = 32)
HMAC: HMAC-SHA256 签名 (32 字节)
FIXDATA: 固定数据 (21 字节)
```

HMAC 计算方式：
- 密钥：USERNAME + MD5(PASSWORD) 的十六进制字符串
- 消息：4 字节质询值
- 算法：HMAC-SHA256

固定数据（21 字节）：
```
14 01 01 01 02 04 00 00 00 00 03 02 27 10 04 01 01 05 02 00 04
```

握手过程：
1. 客户端发送：`0x05 0x01 0x82`（XOR 后：`0xFA 0xFE 0x7D`）
2. 服务器响应：`0x05 0x82 [4 字节质询]`
3. 客户端发送认证包（75 字节，XOR 混淆）
4. 服务器响应：`0x01 0x00`（成功）或其他（失败）

## 配置信息获取
接入点和认证信息可以通过其 Windows 客户端的日志文件查看，位置在 `[安装位置]\client\log\redirector.log`，示例如下：
```
Thu Jul 31 10:57:16 2025 | INFO | [SpeedupDriverApi.cpp:212] : Begin to install driver.
Thu Jul 31 10:57:16 2025 | INFO | [SpeedupDriverApi.cpp:244] : Success to copy file to dest folder 
Thu Jul 31 10:57:16 2025 | INFO | [SpeedupDriverApi.cpp:253] : Success to install driver.
Thu Jul 31 10:57:21 2025 | INFO | [SpeedupDriverApi.cpp:212] : Begin to install driver.
Thu Jul 31 10:57:21 2025 | INFO | [SpeedupDriverApi.cpp:244] : Success to copy file to dest folder 
Thu Jul 31 10:57:21 2025 | INFO | [SpeedupDriverApi.cpp:253] : Success to install driver.
Thu Jul 31 10:57:21 2025 | INFO | [SpeedupDriverApi.cpp:23] : Begin to start acc 
Thu Jul 31 10:57:21 2025 | DEBUG | [SocksRedirector.cpp:115] : Begin to init eventhandler, version = 1.0.20240929.1608
Thu Jul 31 10:57:21 2025 | DEBUG | [SocksRedirector.cpp:100] : Begin to parse json. json: {"game_info":{"game_exe":"chrome.exe,msedge.exe,Zoom.exe,iexplore.exe,firefox.exe,opera.exe,360se.exe,360ChromeX.exe,QQBrowser.exe,SogouExplorer.exe,UCBrowser.exe","region_id":"10000","line_id":"1","optionJson":"only_acc_white:true"},"option":{"default_acc":true,"default_http_acc":true,"limit_speed":10},"server":[{"tag":"default","url":"cmcc://36.134.36.231:10800?udp_port=10800\u0026usr=1234567899876543210\u0026passwd=pAssWord"},{"server_id":1,"tag":"download","url":"cmcc://36.134.36.231:10800?udp_port=10800\u0026usr=1234567899876543210\u0026passwd=pAssWord"},{"server_id":2,"tag":"s5","url":"cmcc://36.134.36.231:10800?udp_port=10800\u0026usr=1234567899876543210\u0026passwd=pAssWord"},{"server_id":3,"tag":"direct","url":"cmcc://36.134.36.231:10800?udp_port=10800\u0026usr=1234567899876543210\u0026passwd=pAssWord"}],"dns_rule":{}}
Thu Jul 31 10:57:24 2025 | ERROR | [GameAccConf.cpp:620] : loadGlobalBlack open file failed , err:2
Thu Jul 31 10:57:24 2025 | INFO | [CmccThread.cpp:8] : Begin to init CMCC ConfHandler thread
Thu Jul 31 10:57:24 2025 | INFO | [CmccThread.cpp:24] : Success to init CMCC ConfHandler thread
Thu Jul 31 10:57:24 2025 | DEBUG | [iocp.h:98] : IOCP workerThread = 7320
Thu Jul 31 10:57:24 2025 | DEBUG | [tcpproxy.cpp:424] : TCPProxy::init port=8888
Thu Jul 31 10:57:24 2025 | DEBUG | [iocp.h:98] : IOCP workerThread = 3776
Thu Jul 31 10:57:24 2025 | DEBUG | [tcpproxy.cpp:449] : TCPProxy::init IPv4 listen socket initialized
```
其中的 `cmcc://36.134.36.231:10800?udp_port=10800&usr=1234567899876543210&passwd=pAssWord` 就是代理服务器配置：
- 服务器地址：`36.134.36.231`
- 服务器端口：`10800`
- 用户名：`1234567899876543210`
- 密码：`pAssWord`

也可以通过抓包 iOS 请求获取：
URL：`https://aifast.komect.com/portal/education/pc/checkSdkPermission`
```json
{
     "data": {
          "accountId": "1234567899876543210",
          "custId": "1234567899876543210",
          "hasPermission": "1",
          "netInfo": "AA=",
          "rightType": "3",
          "signature": "FFFFFFF",
          "supportUnsub": "0",
          "timestamp": "1754989161484",
          "url": "https://aifast.komect.com/portal/#/pc/pages/taPackage?type=hyta"
     },
     "resultCode": 100000,
     "resultDesc": "请求成功"
}
```
其中 `data.netInfo` 是使用 AES-128-CBC 加密的，Key：`8cc72b05705d5c46`，IV：`667b02a85c61c786`，解密后：
```json
[
     {
          "accountType": 1,
          "lns": "223.109.209.219",
          "name": "pop_sh",
          "ordernum": 1,
          "password": "pAssWord",
          "user": "1234567899876543210"
     },
     {
          "accountType": 1,
          "lns": "223.109.209.219",
          "name": "pop_gz",
          "ordernum": 1,
          "password": "pAssWord",
          "user": "1234567899876543210"
     },
     {
          "accountType": 1,
          "lns": "223.109.209.219",
          "name": "pop_bj",
          "ordernum": 1,
          "password": "pAssWord",
          "user": "1234567899876543210"
     }
]
```

经过测试，收集到的接入点以及认证方式如下：
| 接入点                | 接入点区域 | 认证方式 | 落地区域                       |          |
| --------------------- | ---------- | -------- | ------------------------- | -------- |
| 223.109.209.219:10800 | 上海移动   | 0x80     | 腾讯云上海                   |          |
| 36.134.36.231:10800   | 上海移动   | 0x82     | 腾讯云上海 or 腾讯云香港       | 自动分流  |
| 36.134.129.66:10800   | 北京移动   | 0x80     | 北京移动                     |          |
| 36.134.129.66:10800   | 北京移动   | 0x82     | 腾讯云上海 or 腾讯云香港       | 自动分流  |

## 使用
由于此协议不同于标准 SOCKS5，所以不能直接用在 Surge 或其他类似软件上，目前有两种使用方式：
1. 使用 Docker 运行在 NAS 或主机上
2. 修改 Mihomo 内核，新增此协议支持

第二种方式难度较高，我这里简单实现了一个 SOCKS5 to CMCC 的转发器，使用方法：
```bash
docker run -d \
    --name janus-proxy \
    --network host \
    -v ./config.json:/root/config.json \
    codming/janus:latest
```

配置文件 `config.json`:
```json
{
  "listen_addr": "0.0.0.0:10808",
  "remote_addr": "36.134.36.231:10800",
  "username": "1234567899876543210",
  "password": "pAssWord",
  "protocol": "0x82",
  "log_level": "info",
  "connection_timeout": 30,
  "max_connections": 1000,
  "buffer_size": 524288
}
```

Surge 配置示例：
```
[Proxy]
CMCC = socks5, 127.0.0.1, 10808, test-url=http://223.5.5.5
```

## 总结
我目前主要用来绕过中国移动云盘的跨运营商限速。一般在晚上的时候，电信或联通宽带下载中国移动云盘资源的速度很慢，让 `*.cmecloud.cn` 走这个代理，速度能提升不少。

另外发现这个用户名和密码不会过期，即使开通的加速服务到期了，也能继续使用这个账号进行代理连接。其他用途还没有发现，感兴趣的可以自己测试。
