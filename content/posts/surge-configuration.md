---
title: "分享我的 Surge 配置文件"
date: 2023-01-31T15:16:22+08:00
tags: ["Surge", "工具"]
keywords: ["Surge", "代理", '网络']
description: "使用 Surge 作为代理工具，可以让你的网络访问更加稳定，本文将分享我的 Surge 配置文件。"
draft: false
---

如果你平时使用的设备是 Mac 和 iPhone 的话，我比较推荐使用 [Surge](https://nssurge.com/) 来优化你的网络访问，

如果直接在 Surge 中使用订阅的配置，自定义一些规则和更新接入点信息是不兼容的，因为每次更新订阅之后，以前对配置文件的修改将被覆盖。由于 Surge 支持外部策略，也支持外部的规则集，利用这两点，我们可以自行编写配置文件，将订阅更新与自定义规则结合起来，还可以合并多个服务商订阅或者自建服务器。

## Surge 配置文件
```confß
[General]
# General
internet-test-url = http://taobao.com
proxy-test-url = http://1.1.1.1/generate_204
test-timeout = 3
ipv6 = false
show-error-page-for-reject = true
loglevel = notify
skip-proxy = 127.0.0.1, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 100.64.0.0/10, 17.0.0.0/8, localhost, *.local, *.crashlytics.com, 240e:cf:9000::/48
# DNS
dns-server = 223.5.5.5, 223.6.6.6
encrypted-dns-server = https://223.5.5.5/dns-query
exclude-simple-hostnames = true
# Advanced
use-default-policy-if-wifi-not-primary = false
allow-wifi-access = false
http-api-web-dashboard = true
geoip-maxmind-url = https://cdn.jsdelivr.net/gh/Hackl0us/GeoIP2-CN@release/Country.mmdb
# Others
http-listen = 0.0.0.0
socks5-listen = 0.0.0.0

[Replica]
hide-apple-request = true
hide-crashlytics-request = true
hide-udp = false
keyword-filter-type = false

[Proxy]
Direct = direct

[Proxy Group]
Proxy = select, Hong Kong, Japan, Singapore, USA, Direct
Hong Kong = url-test, policy-path=<Node List URL>, update-interval=259200, policy-regex-filter=Hong Kong\s*[0-9]*$, interval=1200, tolerance=5, timeout=3
Japan = url-test, policy-path=<Node List URL>, update-interval=259200, policy-regex-filter=Japan\s*[0-9]*$, interval=1200, tolerance=5, timeout=3
Singapore = url-test, policy-path=<Node List URL>, update-interval=259200, policy-regex-filter=Singapore\s*[0-9]*$, interval=1200, tolerance=5, timeout=3
USA = url-test, policy-path=<Node List URL>, update-interval=259200, policy-regex-filter=(USA Seattle|USA San Jose)\s*[0-9]*$, interval=1200, tolerance=5, timeout=3
Global = select, Proxy, Direct
Final = select, Proxy, Direct

[Rule]
# > DIY
DOMAIN-SUFFIX,opensubtitles.org,DIRECT
DOMAIN-SUFFIX,openai.com,Japan
DOMAIN,translate.googleapis.com,Proxy
# > Rule-set
RULE-SET,https://cdn.jsdelivr.net/gh/Swilder-M/network_rule@master/ad.list,REJECT,update-interval=259200
DOMAIN-SET,https://cdn.jsdelivr.net/gh/Loyalsoldier/surge-rules@release/private.txt,DIRECT
# DOMAIN-SET,https://cdn.jsdelivr.net/gh/Loyalsoldier/surge-rules@release/reject.txt,REJECT
RULE-SET,SYSTEM,DIRECT
RULE-SET,https://cdn.jsdelivr.net/gh/blackmatrix7/ios_rule_script@master/rule/Surge/GitHub/GitHub.list,Proxy,update-interval=259200
DOMAIN-SET,https://cdn.jsdelivr.net/gh/Loyalsoldier/surge-rules@release/icloud.txt,DIRECT
DOMAIN-SET,https://cdn.jsdelivr.net/gh/Loyalsoldier/surge-rules@release/apple.txt,DIRECT
DOMAIN-SET,https://cdn.jsdelivr.net/gh/Loyalsoldier/surge-rules@release/google.txt,DIRECT
RULE-SET,https://cdn.jsdelivr.net/gh/blackmatrix7/ios_rule_script@master/rule/Surge/Telegram/Telegram.list,Proxy,update-interval=259200
RULE-SET,https://cdn.jsdelivr.net/gh/blackmatrix7/ios_rule_script@master/rule/Surge/Twitter/Twitter.list,Proxy,update-interval=259200
RULE-SET,https://cdn.jsdelivr.net/gh/blackmatrix7/ios_rule_script@master/rule/Surge/YouTube/YouTube.list,Proxy,update-interval=259200
RULE-SET,https://cdn.jsdelivr.net/gh/blackmatrix7/ios_rule_script@master/rule/Surge/Slack/Slack.list,Proxy,update-interval=259200
DOMAIN-SET,https://cdn.jsdelivr.net/gh/Loyalsoldier/surge-rules@release/proxy.txt,Proxy
DOMAIN-SET,https://cdn.jsdelivr.net/gh/Loyalsoldier/surge-rules@release/direct.txt,DIRECT
RULE-SET,https://cdn.jsdelivr.net/gh/Loyalsoldier/surge-rules@release/cncidr.txt,DIRECT,update-interval=259200
RULE-SET,LAN,DIRECT
# > GeoIP China
GEOIP,CN,Direct
FINAL,Proxy,dns-failed

[Host]
mtalk.google.com = 108.177.125.188
services.googleapis.cn = 216.58.200.67
```

## 一些说明
- 此配置是将节点按照区域划分不同的 Proxy Group，然后使用 `url-test` 的方式来选择延迟较低的节点，你只需关心选择哪个区域来上网。

- 配置中的 `policy-path` 需要改成自己的 *Node List URL*，仅包含节点信息，不包含其他信息，可能还需要调整下 `policy-regex-filter`，因为你自己的节点名称格式可能与我的不一致。

- `skip-proxy` 中的 `240e:cf:9000::/48` 是为了解决最新版 Surge 关闭 IPV6 后依旧可以访问纯 IPV6 地址，导致 QQ 无法接收图片，如果你的网络支持 ipv6，可以将其删除。

- 自定义规则应尽量减少 DNS 查询，Surge 规则匹配是自上而下的，所以你可以将域名规则或者纯 IP 规则放在靠前位置，需要 DNS 查询的规则放到靠后位置，这样可以有效减少 DNS 查询的次数。

- 外部策略和规则集会自动更新，如果有需要，你也可以通过 Surge 软件的*外部资源*功能来手动更新。

- 配置文件隐去了一些我自己的规则，如果你有需要，可以自行在 Rule 增加。例如：让 Netflix 请求全部通过新加坡访问，可以在 Rule 中增加以下内容：
  ```
  RULE-SET,https://cdn.jsdelivr.net/gh/blackmatrix7/ios_rule_script@master/rule/Surge/Netflix/Netflix.list,Singapore,update-interval=259200
  ```

## 参考
- [Surge 文档](https://manual.nssurge.com/)
- [最小配置推荐](https://community.nssurge.com/d/1214)
- [一些常用网站或 APP 规则集](https://github.com/blackmatrix7/ios_rule_script)
