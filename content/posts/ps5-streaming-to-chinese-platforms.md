---
title: "PS5 无采集卡推流国内直播平台完整教程"
date: 2025-07-03T21:00:00+08:00
tags: ["PS5", "直播", "推流", "Twitch", "Surge", "Docker", "PStream", "网络劫持"]
keywords: ["PS5", "直播推流", "无采集卡", "Twitch劫持", "PStream", "Docker", "Surge", "网络代理", "RTMP", "nginx", "B站直播", "斗鱼直播", "OBS", "轻量级直播方案"]
description: "无需采集卡，通过 Surge 网络劫持和 Docker PStream 服务，将 PS5 的 Twitch 推流重定向到国内直播平台（B站、斗鱼等）的完整技术教程，适合轻量级游戏直播需求。"
draft: false
---

PlayStation 5 自带的直播功能仅限 Twitch 和 YouTube 平台，如果想要在国内直播平台（斗鱼、B站、抖音等）进行游戏直播，一般情况下需要借助采集卡，将游戏画面采集到电脑上，然后通过 OBS 进行推流。但对于轻量级玩家来说，采集卡并非必需品。

下面演示一个更加便捷的方案。这个方法其实在 2021 年或更早之前就已经存在，但很多教程要求较好的 Linux 操作基础，或者版本比较旧，这里我重新整理一下。

首先需要检查以下前提条件：
- PS5 已关联 Twitch 账号
- 软路由或安装了代理软件的电脑
- 可运行 Docker 的设备（可以与上一步的设备是同一台）

下面以 Mac mini + Surge 为例。

## 网络配置
我的主路由是华硕 AX86U（192.168.50.1），Mac mini（192.168.50.16）安装了 Surge，PS5 的网络设置如图：

![PS5 网络设置](https://static.codming.com/img/20250703174656280.png)
> Surge 作为网关的情况下，DNS 需要设置为 198.18.0.2，如果是 Openwrt，则网关地址和 DNS 均设置为 Openwrt 的 IP 地址

## 关联 Twitch 账号
在 PS5 的设置中，找到用户和账号，关联的服务里选择 Twitch，按照提示操作即可。

![关联 Twitch 账号](https://static.codming.com/img/20250703174923506.png)

## 检查 Twitch 推流服务器
在开始配置 Docker 之前，需要先获取到你的 Twitch 账号对应的推流服务器。在 PS5 上随便打开一个游戏，点击手柄上的播放分享键，选择播放服务商为 Twitch，修改分辨率为 1920*1080，60fps，然后点击开始直播。在 Mac mini 的 Surge 请求查看器中筛选包含 `live-video.net` 的请求，如下图所示，我的推流服务器为 `ingest.global-contribute.live-video.net:1935`，记下这个域名，稍后需要劫持它。

![检查 Twitch 推流服务器](https://static.codming.com/img/20250703175624733.png)

## 配置 Surge 劫持 Twitch 推流服务器
在 Surge 的配置文件中，添加以下配置：
```
[Host]
ingest.global-contribute.live-video.net = 192.168.50.16
```
注意：这里的 `ingest.global-contribute.live-video.net` 需要替换为上一步获取到的推流服务器域名，`192.168.50.16` 需要替换为你的 Mac mini 的 IP 地址。

## 安装 PStream
```shell
sudo docker run -d -it --name pstream -p 8080:8080 -p 1935:1935 --restart always codming/pstream
```

8080 端口用于状态监控，1935 端口用于推拉流。容器启动后，可以通过 `http://192.168.50.16:8080` 查看状态。

## 获取 RTMP URL
在 PS5 上开启直播，查看状态监控页面，可以看到有一个 live_XXXX 的 stream，点击名称即可复制 RTMP URL，例如 `rtmp://192.168.50.16:1935/app/live_XXXX`。这里的 ID 不要泄漏给任何人，如果不慎泄漏，需要前往 [Twitch 创作者仪表板](https://dashboard.twitch.tv/settings/stream) 修改密钥。
![状态监控](https://static.codming.com/img/20250703204913068.png)

## 推流到国内直播平台
到目前为止，你的 PS5 已经可以正常地将画面推流到 PStream 服务器了，接下来有两种方案：

### 方案一：使用 OBS 推流
1. 下载并安装 [OBS Studio](https://obsproject.com/download)
2. 打开 OBS，在源中添加一个媒体源，取消勾选"本地文件"，在"输入"中填写 RTMP URL，点击"确定"
3. 回到主界面，你将看到 PS5 的游戏画面，点击右侧的"开始直播"按钮，即可开始推流

### 方案二：使用 PStream 直接 Push 到直播平台
在运行 PStream 的设备上，找一个固定位置，例如 `/opt/pstream`，将 GitHub 上最新的 [nginx.conf](https://github.com/Swilder-M/docker-images/blob/master/pstream/nginx.conf) 文件复制或下载到该目录下，然后编辑它，例如：
```nginx
# 其他配置省略，不用修改
rtmp {
    server {
        listen 1935;
        application app {
            live on;
            push rtmp://live-push.bilivideo.com/live-bvc/?args;
        }
    }
}
# 后续省略
```
配置中的 `rtmp://live-push.bilivideo.com/live-bvc/?args` 需要替换为你要直播的平台推流地址，然后使用以下命令重新运行 PStream：
```shell
sudo docker stop pstream
sudo docker rm pstream
sudo docker run -d -it --name pstream -p 8080:8080 -p 1935:1935 -v /opt/pstream/nginx.conf:/etc/nginx/nginx.conf --restart always codming/pstream
```

## Bilibili 推流地址获取
B站最新规则限制只有 5000 粉以上的 Up 主才可以使用第三方推流，但我们可以利用插件 [B站推流码获取工具](https://greasyfork.org/zh-CN/scripts/536798-b%E7%AB%99%E6%8E%A8%E6%B5%81%E7%A0%81%E8%8E%B7%E5%8F%96%E5%B7%A5%E5%85%B7) 获取推流码。

Enjoy!
