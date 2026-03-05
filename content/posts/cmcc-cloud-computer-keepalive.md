---
title: "中国移动云电脑远程连接协议和保活机制分析"
date: 2026-03-05T19:00:00+08:00
tags: ["逆向工程", "网络协议", "SPICE", "云电脑", "保活"]
keywords: ["移动云电脑", "SPICE协议", "SCG网关", "穿云SDK", "ChuanyunHead", "AES-CTR", "保活", "协议逆向", "Trunk多路复用", "Display Surface"]
description: "深度逆向分析中国移动云电脑的远程连接协议栈：SOHO/CEM API 签名与加密机制、SCG 网关 AES-128-CTR 认证包构造、穿云 ChuanyunHead 24 字节帧头 Trunk 多路复用，以及 SPICE 协议握手全流程。通过逐层实验定位保活关键：必须完成 Display Surface 创建（DISPLAY_INIT），仅建立连接或通道认证均不足以阻止 30 分钟自动关机。"
draft: false
---

> 声明：本文内容仅供学习和研究使用，请勿用于非法用途，作者不对因使用本文内容而产生的任何后果负责。

首先了解一下中国移动云电脑的基本情况，来自中国移动官方网站的介绍：
> 移动云电脑是中国移动智慧家庭中心基于云计算和虚拟化技术推出的安全、便捷的云端虚拟桌面服务。用户可以通过网络使用个人的设备登录软客户端（电脑、平板、手机）或使用中国移动联合授权的硬件设备（口袋电脑、便携主机、云笔电、PAD、一体机）访问云上电脑系统，就可以如同使用一台自己的传统电脑一样，在云电脑桌面上自行安装或者使用已安装好的应用软件进行娱乐、办公、学习等。

在实际使用中，我们知道云电脑需要持续保持与服务器的连接，如果关闭了连接，在一段时间后（通常是 30 分钟），云电脑会自动关机，这对于挂机或者运行长时间任务的用户来说是非常不方便的，所以我对中国移动云电脑的远程连接协议和保活机制进行了分析，以下是分析结果和简要过程：

## 整体架构

在开始拆解协议之前，首先了解下整体架构。移动云电脑并不是简单的"客户端直连虚拟机"，中间经过了多层封装和代理。以 macOS 客户端为例，整个通信链路涉及以下组件：

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                         macOS Client (Electron App)                          │
│                                                                              │
│ ┌────────────────┐  auth  ┌────────────────┐ NxTCP  ┌─────────────────┐      │
│ │  Main Process  │ ─────▶ │  SPICE Client  │ ─────▶ │  Chuanyun SDK   │      │
│ │  (JavaScript)  │        │(ZTE uSmartView)│  via   │(jwae.framework) │      │
│ │                │        │                │ :10800 │                 │      │
│ │ - SOHO Login   │        │main / display /│ local  │AES-CTR Auth+TLS │      │
│ │ - CEM Boot VM  │        │ inputs/cursor  │        │ Trunk Multiplex │      │
│ │ - Heartbeat    │        │ (per-channel)  │        │ NxTCP -> 1xTCP  │      │
│ └────────────────┘        └────────────────┘        └────────┬────────┘      │
└──────────────────────────────────────────────────────────────┼───────────────┘
                                                               │
                                                       1xTCP : SCG:10800
                                                               │
                                               ┌───────────────▼───────────────┐
                                               │  SCG Gateway ──▶ Cloud PC VM  │
                                               │(Secure Connect) (SPICE Server)│
                                               └───────────────────────────────┘
```


几个关键角色：

| 缩写 | 全称 | 职责 |
|------|------|------|
| **SOHO** | Small Office Home Office | 中国移动云服务平台，负责用户登录、设备列表、心跳等业务 API |
| **CEM** | Cloud Enablement Manager | 云电脑管理平台，负责 OAuth 认证、开机指令、连接信息下发 |
| **SCG** | Secure Connect Gateway | 安全连接网关，远程桌面数据流的入口 |
| **穿云 SDK** | Chuanyun SDK | 传输中间件，负责 SCG 认证、TLS、Trunk 多路复用 |
| **SPICE** | Simple Protocol for Independent Computing Environments | 远程桌面协议，被定制为 GSpice 运行在穿云 Trunk 之上 |


客户端的 Electron 主进程负责所有 HTTP API 调用（登录、获取连接信息、心跳上报），而实际的远程桌面数据流则经过**穿云 SDK → SCG 网关 → 云电脑 VM** 这条路径。穿云 SDK 的核心作用是将 SPICE 客户端发出的多条 TCP 连接，通过自定义的帧头封装，复用到一条 TCP 连接上，再通过 SCG 网关路由到后端的虚拟机。

理解了这个架构，接下来我们就按连接建立的时序，逐层分析每个环节的协议细节。

## API 层：从登录到获取连接信息

### 登录与 Token 体系

移动云电脑的 API 层采用双平台设计：SOHO 平台处理用户身份，CEM 平台处理云电脑业务。两者通过 Token 桥接。

客户端支持短信验证码、密码、扫码等多种登录方式，登录成功后获得 `SohoToken`。这个 Token 长期有效，是后续所有 API 调用的身份凭证。

有了 SohoToken，每次连接云电脑时需要经过一个 Token 交换链：

```
SohoToken ─→ getFirmAuth ─→ scAuthCode (短期凭证)
                                │
                                ▼
                      CEM oauth/token ─→ access_token (12h有效)
                                │
                                ▼
                      getConnectInfo ─→ SCG 连接信息 + 新的 scAuthCode
```

这个设计的意图很明确：SohoToken 是长期凭证，不能直接暴露给 SCG 网关；scAuthCode 是一次性的短期凭证，即使被截获也很快过期。

### API 请求签名

SOHO 平台的每个请求都需要 HMAC-SHA256 签名。客户端在每个请求中携带一组 `X-SOHO-*` 自定义 Header，包含应用标识、设备信息、时间戳等参数，然后将这些参数与请求路径、请求体一起拼接成签名字符串，使用硬编码的密钥计算 HMAC-SHA256。

签名涉及的 Header 字段如下（**顺序很重要**）：

| Header | 含义 | 示例值 |
|--------|------|--------|
| `X-SOHO-AppKey` | 应用标识 | 每个平台的客户端不同 |
| `X-SOHO-AppType` | 设备类型 | `mac\|25.3.0\|MacBookPro\|1\|-1\|{device_id}\|` |
| `X-SOHO-ClientVersion` | 客户端版本 | `2.18.21` |
| `X-SOHO-DeviceId` | 设备唯一标识 | 首次运行时随机生成 |
| `X-SOHO-RomVersion` | 系统版本 | `Apple Inc.-25.3.0` |
| `X-SOHO-SohoToken` | 用户 Token | 登录后获得，未登录时为空 |
| `X-SOHO-Timestamp` | 毫秒时间戳 | `1741153079000` |
| `X-SOHO-UserId` | 用户 ID | 登录后获得，未登录时为空 |
| `X-SOHO-Uuid` | 请求唯一 ID | `uuid_{随机hex}` |
| `X-SOHO-VersionNum` | 版本号 | `2182100` |

签名构造的 Python 演示：

```python
import hmac, hashlib

APP_SECRET = bytes.fromhex('...')  # 从客户端提取的 HMAC 密钥

def soho_sign(method, path, headers_list, body_data=None):
    # 1. 按插入顺序拼接所有非空 Header
    parts = []
    for key, value in headers_list:
        if value:  # 跳过空值（未登录时 SohoToken/UserId 为空）
            parts.append(f'{key}={value}')

    # 2. 构造签名字符串: "{METHOD}&{path}&{k1=v1&k2=v2&...}"
    sign_str = f'{method}&{path}&{"&".join(parts)}'

    # 3. 如果有请求体，追加 "&body={body_data}"
    if body_data:
        sign_str += f'&body={body_data}'

    # 4. HMAC-SHA256
    return hmac.new(APP_SECRET, sign_str.encode(), hashlib.sha256).hexdigest()
```

这里有两个逆向时容易踩的坑：

1. **Header 拼接顺序不是字典序**，而是 JS 代码中对象属性的插入顺序。如果按字母排序拼接，签名会校验失败。
2. **空值要跳过**：未登录时 `SohoToken` 和 `UserId` 为空字符串，这两个字段不参与签名拼接。登录成功后才会加入。

签名计算完成后，将结果放入 `X-SOHO-Signature` Header 中随请求发送。

### 请求体加密

SOHO 平台的请求体并非明文发送，而是经过了一层 RSA 加密封装。整个流程如下：

1. **构造业务 JSON**：例如 `{"phone":"18800001234"}`
2. **RSA 加密**：使用客户端内嵌的 RSA-1024 公钥，以**无填充（textbook RSA）**方式加密，得到 Base64 字符串
3. **包装为标准格式**：将加密后的字符串放入 `data` 字段，最终请求体为 `{"data":"base64_encrypted_string"}`
4. **签名使用加密后的值**：签名时 `body` 参数是加密后的 Base64 字符串，不是原始明文

用伪代码表示：

```python
# 1. 业务数据 RSA 加密（无填充，直接 m^e mod n）
encrypted = base64(rsa_raw_encrypt(json.dumps({"phone": "18800001234"})))

# 2. 加密后的值参与签名
signature = soho_sign('POST', '/login/sms/send/v1', headers, body_data=encrypted)

# 3. 最终请求体
body = json.dumps({"data": encrypted})
```

无填充 RSA 在密码学上并不安全（相同明文总是产生相同密文，且具有乘法同态性），但配合 HTTPS 传输层加密使用倒也勉强够用。

### CEM 平台 API

CEM 平台的 API 风格与 SOHO 不同，它使用标准的 OAuth 2.0 Bearer Token 认证，不需要签名。请求中携带一组自定义 Header 标识客户端身份：

| Header | 含义 | 示例值 |
|--------|------|--------|
| `Authorization` | OAuth access_token | `Bearer eyJhbGci...` |
| `gzs-client-id` | 客户端标识 | 硬编码在客户端二进制中 |
| `gzs-timestamp` | 毫秒时间戳 | `1741153079000` |
| `sc-terminal-sn` | 设备序列号 | 同 SOHO DeviceId |
| `sc-network-type` | 网络类型 | `2` |
| `sc-unit-type` | 设备型号 | `MacBookPro` |

CEM 平台的请求体加密使用另一 RSA-1024 公钥，采用 **PKCS#1 v1.5 填充**，相对规范。加密后的字符串带 `{rsa}` 前缀标识：

```python
# CEM RSA 加密（PKCS#1 v1.5 填充）
encrypted = '{rsa}' + base64(pkcs1_v1_5_encrypt(vm_id))

# 请求体直接使用加密值
body = json.dumps({"vmId": encrypted})
```

获取 CEM access_token 的过程需要两步桥接：先通过 SOHO 的 `getFirmAuth` 接口用 SohoToken 换取 `scAuthCode`，再用这个 scAuthCode 作为 token 调用 CEM 的 OAuth 接口（`/gzs/auth/oauth/token`，标准的 form-urlencoded 格式）获取 `access_token`，有效期 12 小时。

### 开机与连接信息

拿到 CEM access_token 后，调用 `getConnectInfo` 接口，这个调用会触发虚拟机开机（如果尚未运行），并返回关键的连接参数：

- **scgIp / scgPort**：SCG 网关的地址和端口
- **scAuthCode**：用于 SCG 认证的一次性凭证（JWT 格式，约 400 字符）
- **traceId**：开机追踪 ID，用于轮询 VM 就绪状态

如果 VM 尚未就绪，客户端会轮询 `getVmReadyStatus` 直到 `readyStatus=1`，通常需要几秒到几十秒不等。

## SCG 网关认证：穿云 AES 加密包

通过抓包分析，客户端不是直接把 scAuthCode 明文发给 SCG，而是要构造一个特殊的加密认证包。

### 认证包加密算法

对 macOS 客户端中 `jwae.framework`（一个 Rust 编写的穿云库）进行逆向分析（IDA 静态分析 + DYLD hook 动态验证），确定了认证包的加密算法为 **AES-128-CTR**。加密密钥和初始计数器值都是硬编码在二进制文件中的固定常量。

### 认证包结构

认证包的格式如下：

```
[0]       0x01              协议标识（未加密）
[1]       base_id           校验字节 = 密文长度 % 256（未加密）
[2:end]   AES-128-CTR 密文   全部加密
```

密文解密后的明文结构：

```
[0:2]     0x00 0x02         版本号
[2:10]    timestamp         Unix 时间戳，8 字节大端序
[10]      0x03              TLV type（认证信息标记）
[11:13]   length            TLV value 长度，2 字节大端序
[13:N]    scAuthCode        getConnectInfo 返回的凭证
[N:]      "|" + vmId        管道符分隔的虚拟机 ID
```

将这个数据包通过 TCP 发送到 SCG 的 10800 端口后，服务端返回 128 字节的响应。第一个字节为 `0x00` 表示认证成功，此时从响应的固定偏移位置可以提取到一个 `session_id`（3 字节），这个值在后续所有通信中都会用到。

### TLS 升级

认证成功后，TCP 连接直接升级为 TLS（类似 STARTTLS 模式），后续所有数据都在 TLS 隧道中传输。实测使用的是 TLS 1.3。

## 穿云 Trunk 协议：单连接多路复用

标准的 SPICE 协议中，每个通道（main、display、inputs、cursor 等）各自使用独立的 TCP 连接。但在移动云电脑的架构中，客户端到 SCG 只有一条 TCP 连接。穿云 SDK 通过一个自定义的帧头 **ChuanyunHead** 实现了通道多路复用。

### ChuanyunHead 帧格式（24 字节）

```
偏移     大小    含义
[0]      1B      version = 0x01
[1]      1B      type
[2:4]    2B      payload_len（小端序）
[4:8]    4B      reserved = 0
[8:16]   8B      field1 = session_id
[16:24]  8B      field2 = channel_id
```

其中 `type` 字段的含义：

| type | 含义 |
|------|------|
| 1 | 数据帧（SPICE 协议数据） |
| 2 | 控制/统计帧（Welcome、Stats） |
| 3 | 通道关闭通知（"server close"） |

`field2` 是通道多路复用的关键，它标识了这个帧属于哪个 SPICE 通道：

| field2 | 通道 |
|--------|------|
| 1 | main（主控制通道） |
| 2 | display（显示通道） |
| 3 | inputs（键鼠输入） |
| 4 | cursor（光标） |
| 5 | playback（音频播放） |
| 6 | record（音频录制） |

例如，发送 SPICE 主通道的数据包：
```
ChuanyunHead(type=1, field1=session_id, field2=1) + SPICE 消息
```

发送 display 通道的数据包：
```
ChuanyunHead(type=1, field1=session_id, field2=2) + SPICE 消息
```

SCG 网关根据 `field2` 的值，将数据路由到虚拟机上对应的 SPICE 通道。

### 与标准 SPICE 的对比

|      | 标准 SPICE               | 移动云电脑                      |
|------|------------------------|----------------------------|
| 连接方式 | 每个通道独立 TCP 连接          | 单条 TCP + ChuanyunHead 多路复用 |
| 端口   | 通常 5900（明文）或 5901（TLS） | SCG 10800                  |
| 加密   | 可选 TLS                 | 先 AES 认证，再 TLS             |
| 通道注册 | 每条 TCP 连接自成通道          | field2 字段区分                |

这种设计对客户端来说是透明的：SPICE 客户端仍然以为自己在与多个独立的 TCP 端点通信（实际上连接的是本地穿云代理 `127.0.0.1:10800`），穿云 SDK 在本地完成了连接合并和帧封装。

## SPICE 协议握手：从 REDQ 到 Surface 创建

穿过了 SCG 认证和穿云 Trunk 层，接下来就是标准 SPICE 协议的领域了，只不过所有消息都被 ChuanyunHead 封装。

### 标准 SPICE 握手回顾

在标准 SPICE 中，每个通道的建立都遵循相同的四步握手：

1. **客户端发送 SpiceLinkMess**：以 magic `REDQ`（`0x51444552`）开头，包含协议版本、connection_id、channel_type 和能力协商位图
2. **服务端回复 SpiceLinkReply**：同样以 `REDQ` 开头，包含 RSA-1024 公钥（162 字节 DER 格式）和服务端能力位图
3. **客户端发送 128 字节认证 Ticket**：使用服务端公钥以 RSA-OAEP 加密密码（无密码时加密空字节）
4. **服务端返回 4 字节结果**：`0x00000000` 表示认证成功

这个流程在移动云电脑中完全保留，只是每个 SPICE 消息都要套一层 ChuanyunHead。

### 主通道握手

连接 TLS 后，首先收到一个 Welcome 帧（ChuanyunHead type=2），从中提取 `session_id`。然后开始主通道（channel_id=1）的 SPICE 握手：

```
客户端                                  服务端
  │                                       │
  │◄── ChuanyunHead(type=2) Welcome ──────│  获取 session_id
  │                                       │
  │───── ExtInfo + [token + REDQ] ───────▶│  主通道握手请求
  │                                       │
  │◄───── REDQ Reply (含 RSA 公钥) ────────│  218B，含 162B RSA-1024 公钥
  │                                       │
  │─── auth_type(1) + RSA-OAEP(空密码) ───▶│  128B 加密 ticket
  │                                       │
  │◄──────── auth_result = 0 ─────────────│  认证成功
  │                                       │
  │◄──────── MAIN_INIT (0x67) ────────────│  含 spice_session_id
  │                                       │
  │───── ClientInfo + ATTACH_CHANNELS ───▶│  请求通道列表
  │                                       │
  │◄────── CHANNELS_LIST (0x68) ──────────│  可用通道列表
```

这里有一个细节：在标准 SPICE 中，SpiceLinkMess 是通道握手的第一个消息。但在穿云协议中，客户端会先发一个 22 字节的 **ExtInfo** 消息（包含通道类型标识），然后才是 16 字节随机 token + 标准的 REDQ。这个 ExtInfo 可能是穿云 SDK 添加的扩展，用于让 SCG 网关识别通道类型。

### 能力协商与 Mini Header

标准 SPICE 支持两种消息头格式：**Full Header**（18 字节，含 serial 和 sub_list）和 **Mini Header**（6 字节，仅 type + size）。当双方在能力位图中都声明支持 `SPICE_COMMON_CAP_MINI_HEADER`（bit 3）时，后续消息使用更紧凑的 Mini Header。

在移动云电脑的实现中，SPICE 消息全部使用 Mini Header 格式：

```
Mini Header (6 bytes):
  UINT16  type    消息类型 ID
  UINT32  size    载荷大小
```

此外，主通道和 display 通道的 REDQ 中携带了 channel_caps（通道特定能力），而 inputs 和 cursor 通道则没有，这与标准 SPICE 的行为一致，因为输入和光标通道的功能集相对固定，不需要额外的能力协商。

### 子通道连接

收到 CHANNELS_LIST 后，客户端需要连接子通道。在标准 SPICE 中，这意味着为每个子通道建立新的 TCP 连接，每条连接都走一遍完整的 REDQ 握手流程，只是 `connection_id` 使用从 MAIN_INIT 获取的 `spice_session_id`（而非主通道的 0）。

在穿云架构下，子通道不需要新建 TCP 连接，只需要用不同的 `field2` 值发送 ChuanyunHead 帧即可。但有一个重要发现：**并非所有通道都能成功注册**。

通过实验发现，SCG 会自动注册 display（field2=2）通道，但 inputs（field2=3）和 cursor（field2=4）通道的注册会失败。在未注册的通道上发送 SPICE 数据，会导致 SCG 发送 type=3 的 "server close" 帧，**关闭整个会话**，包括已经成功建立的 main 和 display 通道。这个行为比较激进，意味着子通道的连接策略必须非常谨慎。

官方客户端之所以能成功连接所有通道，是因为穿云 SDK 内部有额外的通道注册机制（推测在 Trunk 层面），这部分逻辑没有在网络层面体现为可见的注册消息，应该是 SDK 和 SCG 之间的内部协议。

### Display 通道初始化

Display 通道的握手成功后，客户端需要发送一个关键消息：**DISPLAY_INIT**（`SPICE_MSGC_DISPLAY_INIT`，type=0x65），告诉服务端客户端的图像缓存配置：

```
DISPLAY_INIT (14 bytes payload):
  pixmap_cache_id:            u8   = 1
  pixmap_cache_size:          i64  = 20MB
  glz_dictionary_id:          u8   = 1
  glz_dictionary_window_size: i32  = ~8MB
```

这个消息在标准 SPICE 中也是必须的，它配置了 pixmap 缓存和 GLZ（Global LZ）字典压缩的参数。没有这个消息，服务端不会开始推送屏幕内容。

服务端收到 DISPLAY_INIT 后，返回一系列初始化消息：

```
服务端 → 客户端:
  1. SET_ACK (0x03)           建立滑窗确认机制 (generation=1, window=20)
  2. INVAL_ALL_PALETTES       清除调色板缓存
  3. SURFACE_CREATE (0x013a)  创建主 Surface (720×400, 32bit, primary)
  4. DRAW_COPY (0x0130)       初始屏幕像素数据
  5. MONITORS_CONFIG          显示器配置
  6. MARK (0x66)              渲染完成标记
```

在标准 SPICE 中，`MARK` 消息表示"初始屏幕内容已完整发送，客户端可以开始渲染"。这个信号在移动云电脑中有着更重要的含义，它可能是平台判定"显示会话已建立"的标志。

### 流控机制：SET_ACK / PING

SPICE 的流控采用两个独立的机制：

**ACK 滑动窗口**：服务端通过 `SET_ACK` 设置一个确认窗口（通常 window=20），客户端收到后先回复 `ACK_SYNC` 确认窗口生效，之后每收到 window 条消息就回复一个 `ACK`。这防止了服务端发送过快导致客户端缓冲区溢出。

**PING/PONG**：服务端定期发送 `PING`（含时间戳），客户端回复 `PONG`（回传相同的时间戳）。服务端据此测量往返延迟，如果延迟过高，可能会降低画质（如启用 JPEG 压缩、降低色深等）以减少带宽占用。

在保活场景中，正确响应 PING/PONG 是维持连接不被服务端超时断开的基本要求。

## 保活机制：到底什么决定了 VM 是否关机

经过逐层实验，终于找到了移动云电脑判定"客户端是否在线"的精确条件。

### 逐步实验

| 阶段 | 完成的握手步骤 | VM 是否保持运行 |
|------|--------------|---------------|
| 仅 SCG 认证 + TLS | TCP 连接建立 | ❌ 30 分钟关机 |
| + 主通道 SPICE 握手 | REDQ + RSA auth 成功 | ❌ 30 分钟关机 |
| + display 通道 SPICE 握手 | display auth 成功 | ❌ 30 分钟关机 |
| + **DISPLAY_INIT** | **Surface 创建 + 屏幕推送** | **✅ 保持运行** |

结论非常明确：**平台判定的不是"有没有连接"，而是"显示会话是否完整建立"**。

关键转折点就是 `DISPLAY_INIT` 消息。发送这个消息后，服务端创建 Surface 并开始推送屏幕数据（DRAW_COPY），此时平台才认为有真实的客户端在使用云电脑。仅仅建立连接、完成认证，甚至完成通道握手，都不够。

### 保活策略

基于以上分析，保活策略就很清晰了：

1. **完整走完连接流程**：API Token 获取 → SCG 认证 → TLS → SPICE 主通道握手 → display 通道握手 → DISPLAY_INIT → 等待 Surface 创建完成
2. **维持连接活跃**：正确响应 PING/PONG 和 SET_ACK，定期发送 SOHO 心跳 API
3. **定时重连**：配合 cron 定时任务，在 30 分钟关机倒计时到期前重新建立完整会话

实测中，每 10 分钟建立一次连接并保持 120 秒，VM 可持续运行 24 小时以上。

### 注意事项

在保活实现中有几个坑值得注意：

- **不要尝试连接 inputs/cursor 通道**：在 SCG 未注册的通道上发送数据会导致整个会话被关闭，反而加速 VM 关机（从 30 分钟缩短到约 10 分钟）
- **DISPLAY_INIT 必须在 display auth 成功后立即发送**：延迟过久可能导致服务端超时
- **scAuthCode 有时效性**：每次连接都需要重新通过 API 获取，不能复用

## 逆向过程简述

### macOS 客户端分析

移动云电脑的 macOS 客户端是一个 Electron 应用，没有加壳或反调试保护，分析起来相对友好。

**前端参数提取**：使用 `asar extract` 解包 Electron 资源，在 JS 配置文件中找到 SOHO 平台的 APP_KEY 和签名密钥等参数。

**穿云库逆向**：核心的传输逻辑在 `jwae.framework` 中，这是一个 Rust 编写的动态库。通过 IDA 分析确定了 AES-128-CTR 的加密参数，包括密钥和初始计数器值。Rust 编译的二进制文件符号信息比较丰富（函数名保留了 crate 路径和方法名），大大降低了逆向难度。

**动态验证**：使用 DYLD 环境变量注入自定义 hook 库，拦截 `ChuanyunHead::from_args` 等关键函数，在运行时打印帧参数，最终确认了 ChuanyunHead 各字段的含义。

### 协议抓包

通过 Surge 进行 HTTPS MITM 抓包获取 API 层的请求参数；通过在本地穿云代理端口（127.0.0.1:10800）和外网 SCG 端口同时抓包，得到了 SPICE 协议的明文数据（本地端）和加密数据（外网端）的对照，用 Wireshark 解析标准 SPICE 协议消息。

## 与其他保活方案的对比

在逆向协议之前，我也查了网上已有的保活方案，主要有以下两种：

### 方案一：云电脑内套娃运行客户端

思路是在云电脑的 Windows 系统内安装官方客户端，让云电脑自己连接自己，形成"套娃"。看起来很巧妙，但**这个方案在新版本中已经失效**，平台在云电脑的网络层面屏蔽了 SCG 网关的 IP 地址，从云电脑内部无法建立到自身的远程连接。即使能绕过 DNS，TCP 层面也会被拦截。

### 方案二：Docker 封装 Linux 客户端 + 模拟点击

将官方 Linux 版客户端打包进 Docker 容器，配合 Xvfb 虚拟显示和 xdotool 模拟鼠标点击，让客户端在无头环境中保持运行。这个方案确实可行，但有明显的缺点：

- **资源开销大**：需要运行完整的客户端 + 虚拟 X Server，内存占用较高
- **依赖复杂**：需要维护 Docker 镜像、处理客户端版本更新、配置 Xvfb 和模拟点击脚本
- **稳定性差**：客户端 UI 变化可能导致模拟点击失效，需要反复调试坐标和时序
- **本质是黑盒**：不理解底层协议，出问题时无从排查

### 本文方案：协议级保活

基于协议逆向，用脚本直接模拟 SCG 连接和 SPICE 握手，精确触发 Display Surface 创建。

**优势：**

- **极低资源占用**：单个二进制文件，无 GUI 依赖，运行时内存占用仅约 10MB，适合在任意低配服务器或 NAS 上运行
- **跨平台**：基于 Go 编译，支持 macOS、Windows、Linux（含 ARM/MIPS），覆盖主流 NAS 和路由器
- **高可靠性**：直接对话协议层，不依赖 UI 渲染和模拟点击，不受客户端版本更新影响
- **快速连接**：每次连接只需完成必要的握手步骤（约 2 秒），不需要等待 UI 加载和渲染
- **精确控制**：可以精确控制连接时长、心跳频率、重连策略，配合 cron 实现全自动化
- **可观测性好**：完整的日志系统，连接状态、握手进度、心跳计数一目了然，出问题时容易定位

## 保活工具使用

基于本文的协议分析，我用 Go 重新实现了完整的保活工具，编译为单文件可执行程序，支持多平台。

### 下载

从 [GitHub Releases](https://github.com/Swilder-M/cloudpc-dist/releases) 下载对应平台的二进制文件：

| 平台 | 架构 | 文件名 |
|------|------|--------|
| macOS | Intel | `cloudpc-darwin-amd64` |
| macOS | Apple Silicon | `cloudpc-darwin-arm64` |
| Windows | x86_64 | `cloudpc-windows-amd64.exe` |
| Linux | x86_64 | `cloudpc-linux-amd64` |
| Linux | ARM64 | `cloudpc-linux-arm64` |
| Linux | ARMv7 (32-bit) | `cloudpc-linux-armv7` |
| Linux | MIPS / MIPS LE | `cloudpc-linux-mips` / `cloudpc-linux-mipsle` |

### 登录

```bash
./cloudpc login
```

交互式流程：自动生成设备标识 → 输入手机号 → 发送验证码 → 输入验证码 → 登录 → 获取云电脑信息。配置保存到 `cloud_pc.json`。

### 保活

```bash
# 保持连接 120 秒（默认）
./cloudpc keepalive

# 自定义保持时长
./cloudpc keepalive --duration 60
```

### 配置定时任务

```bash
crontab -e
```

```cron
# 每 10 分钟建立一次连接，保持 120 秒
*/10 * * * * cd /path/to/cloudpc && ./cloudpc keepalive --duration 120 >> keepalive.log 2>&1
```

### 如何连接云电脑

使用保活脚本后，同一账号同一时间只能有一个客户端连接 SCG 网关，因此**无法同时使用官方客户端和保活脚本**。如果需要连接云电脑进行操作，推荐在云电脑内安装内网穿透工具，绕过官方客户端直接访问：

- [frp](https://github.com/fatedier/frp)：经典的内网穿透方案，需要一台有公网 IP 的服务器
- [Tailscale](https://tailscale.com/)：基于 WireGuard 的零配置组网，无需公网服务器
- [Cloudflare Tunnel](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/)：通过 Cloudflare 网络中继，免费且无需公网 IP

这些工具在云电脑内部运行，通过各自的隧道协议与外部建立连接，不经过 SCG 网关，因此不会与保活脚本冲突。日常使用时通过远程桌面或 SSH 连接云电脑，保活脚本在另一台机器上定时运行防止关机，两者互不干扰。

如果你已经将云电脑重装为 Linux，同样可以使用本保活工具，下载对应架构的 Linux 版本即可。

## 总结

移动云电脑的远程连接协议是一个多层封装的体系：HTTP API 层处理身份认证和业务逻辑，穿云层处理传输安全和连接复用，SPICE 层处理远程桌面会话。保活的关键在于 **Display Surface 的完整创建**，这一发现来自逐步剥离协议层、逐个环节实验排除的过程。

从协议设计的角度看，这套架构的安全分层是合理的：短期 Token 避免了长期凭证暴露，AES 认证包防止了凭证明文传输，TLS 保护了后续数据流。穿云 SDK 的 Trunk 多路复用也是一个实用的工程选择，减少了连接数和握手开销。但客户端的 RSA 无填充加密、固定的 AES 密钥等实现细节仍有改进空间。

最终，整个分析过程的核心经验是：**不要假设，逐层验证**。每一层协议都可能有自己的"存活检测"逻辑，只有精确定位到关键触发点（本例中是 DISPLAY_INIT），才能设计出最小化的保活方案。

## 待解决的问题

- **仅测试了家庭云版本**：目前的分析和验证均基于家庭云版云电脑，其他版本的 API 接口和 SCG 认证流程可能存在差异，尚未进行测试。
- **仅实现了短信验证码登录**：官方客户端支持密码登录和扫码登录等多种方式，目前脚本只实现了短信验证码登录，其他登录方式的 API 调用流程还未逆向。

## 参考资料 & 工具

- [SPICE Protocol Specification](https://www.spice-space.org/spice-protocol.html) - SPICE 协议官方规范，本文中标准 SPICE 握手、消息类型、能力协商等内容的主要参考来源
- [IDA Pro](https://hex-rays.com/ida-pro) - 二进制逆向分析工具，用于 jwae.framework 的静态分析
- [Wireshark](https://www.wireshark.org/) - 网络协议分析工具，用于 SPICE 协议抓包和解析
- [Surge](https://nssurge.com/) - macOS 网络调试工具，用于 HTTPS MITM 抓包获取 API 参数
- [CyberChef](https://gchq.github.io/CyberChef/) - 数据编解码和加解密的在线工具，用于验证 AES-CTR 等加密算法
