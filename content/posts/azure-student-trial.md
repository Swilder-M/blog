---
title: "Azure 学生试用申请流程及注意事项"
date: 2023-01-14T02:44:32+08:00
tags: ["Azure", "云服务"]
keywords: ["Azure", "云服务", '教育', 'EDU 邮箱', '学生']
description: "Azure 为学生提供了 12 个月的免费试用，共有 100 美元的免费额度，本文将介绍如何申请 Azure 学生试用，以及开通 Azure 学生试用后的注意事项。"
draft: true
---

通过 cli 开通新加坡区域服务器
```shell
# 创建资源组
az group create --name 资源组名称 --location southeastasia

# 创建虚拟机
az vm create --resource-group 资源组名称 --name VM名称 --image Debian:debian-11:11-gen2:latest --authentication-type password --admin-username VM用户名 --admin-password VM密码 --size Standard_B1s --os-disk-size-gb 64
```
