# MailAssist 全套标准配置与运维作业程序 (SOP 指南)

本文档记录了从零搭建 **MailAssist** 所需的全部凭证获取、企业微信配置、云服务器端口验证及运维全流程。

---

## 目录
1. [多邮箱授权码与应用专用密码获取](#1-多邮箱授权码与应用专用密码获取)
   - [QQ 邮箱授权码](#11-qq-邮箱-16-位授权码)
   - [Gmail 应用专用密码 (App Password)](#12-gmail-应用专用密码-app-password)
   - [网易 163 与高校内部邮箱](#13-网易-163-与高校内部邮箱)
2. [个人免认证企业微信注册与自建应用](#2-个人免认证企业微信注册与自建应用)
   - [免营业执照创建个人团队](#21-免营业执照创建个人团队)
   - [创建自建应用并绑定个人范围](#22-创建自建应用并绑定个人范围)
   - [开启“在个人微信中接收消息” (关键)](#23-开启在个人微信中接收消息-微信插件)
3. [企业微信服务器回调验证与可信 IP 解锁](#3-企业微信服务器回调验证与可信-ip-解锁)
   - [为什么可信 IP 会被锁定](#31-为什么可信-ip-会被锁定)
   - [通过服务器 URL 验证解锁可信 IP](#32-通过接收消息服务器-url-验证解锁)
   - [80 端口冲突解决方案 (Nginx/OpenResty 反向代理)](#33-80-端口冲突解决方案)
4. [Linux 云服务器 Systemd 守护进程运维](#4-linux-云服务器-systemd-守护进程运维)
5. [网络与代理路由最佳实践](#5-网络与代理路由最佳实践)

---

## 1. 多邮箱授权码与应用专用密码获取

第三方邮件客户端必须使用**独立的授权码/应用专用密码**登录，不能使用邮箱的主登录密码。

### 1.1 QQ 邮箱 16 位授权码
1. 电脑浏览器登录 [QQ 邮箱网页版](https://mail.qq.com/)。
2. 顶部点击 **设置** $\rightarrow$ **账户**。
3. 往下滚动找到 **POP3/IMAP/SMTP/Exchange/CardDAV/CalDAV服务**：
   - 开启 **`POP3/SMTP服务`** 和 **`IMAP/SMTP服务`**。
4. 找到 **“生成授权码”**，按照提示使用绑定的手机发送短信（或微信扫码验证）。
5. 页面会弹出一串 **16 位字母授权码**（格式如 `abcdefghijklmnop`）。
6. 将其填入配置文件的 `password` 字段。
   - IMAP 主机：`imap.qq.com`，端口：`993`（开启 SSL）。

### 1.2 Gmail 应用专用密码 (App Password)
因 Google 安全限制，国内直接登录需要应用专用密码：
1. 电脑登录 [Google 账户管理中心](https://myaccount.google.com/)。
2. 左侧点击 **安全性 (Security)**。
3. 确保已开启 **“两步验证 (2-Step Verification)”**（若未开启，按提示绑定手机号开启）。
4. 在两步验证页面下方，找到 **“应用专用密码 (App passwords)”**（或在顶部搜索栏直接搜索 `应用专用密码`）。
5. 输入一个名称（如 `MailAssist`），点击 **“创建 (Create)”**。
6. 屏幕上会显示一段 **16 位黄底字母密码**。
7. 将其复制填入配置文件的 `password` 字段。
   - IMAP 主机：`imap.gmail.com`，端口：`993`（开启 SSL）。
   - *注意：在中国大陆访问 Gmail IMAP 必须配置代理。*

### 1.3 网易 163 与高校内部邮箱
* **163 邮箱**：进入网页版“设置 $\rightarrow$ POP3/SMTP/IMAP $\rightarrow$ 开启客户端授权密码”，生成 16 位字母授权密码。
* **高校/教育邮箱 (.edu.cn)**：大多基于 Coremail 或腾讯企业邮构建，进入网页版设置页面，开启 IMAP/SMTP 协议并获取客户端专用密码。

---

## 2. 个人免认证企业微信注册与自建应用

个人开发者无需任何营业执照即可免费获得微信官方的高级推送接口。

### 2.1 免营业执照创建个人团队
1. 打开 [企业微信官网](https://work.weixin.qq.com/)，点击右上角 **“企业登录 / 免费注册”**。
2. 注册类型选择 **“团队 / 个体”**（此类型**完全不需要**营业执照与认证费）。
3. 企业名称随便填（如 `我的个人助手`），用个人微信扫码即可完成注册。

### 2.2 创建自建应用并绑定个人范围
1. 登录管理后台，进入 **应用管理** $\rightarrow$ 下方自建区点击 **“创建应用”**。
2. 填写应用名称（如 `邮件通知`），上传一个图标。
3. **关键步骤**：**可见范围** 必须点击添加，选择你自己（该企业成员只有你一人）。
4. 创建成功后，进入该应用主页，记录：
   - **`AgentId`**（如 `1000002`）
   - **`Secret`**（点击查看，微信上会收到确认卡片，确认后页面即可复制 Secret）
5. 在后台顶部导航栏点击 **“我的企业”**，滑到最底部复制 **`企业 ID (CorpID)`**（以 `ww` 开头）。

### 2.3 开启“在个人微信中接收消息” (微信插件)
1. 在管理后台顶部点击 **“我的企业”** $\rightarrow$ 左侧菜单进入 **“微信插件”**。
2. 页面会展示一个**二维码**。
3. 用你的**个人手机微信扫码关注**该插件。
4. 确保勾选“在微信中接收消息”。
5. **效果**：你的个人手机微信聊天列表里会出现“企业微信”插件，所有推送均直接在个人微信弹窗展示，手机端**完全无需下载安装企业微信 App**。

---

## 3. 企业微信服务器回调验证与可信 IP 解锁

### 3.1 为什么可信 IP 会被锁定
企微为了防止 API 凭证泄露，要求必须在后台配置发信端的公网 IP（企业可信 IP）。但企微新规要求：**在配置“企业可信 IP”前，强制要求先二选一配置“可信域名”或“设置接收消息的服务器 URL”**。
* **问题**：个人开发者没有企业主体备案的域名，绑定“可信域名”时会被腾讯拦截提示“主体不一致”。
* **突破口**：选择 **“设置接收消息的服务器 URL”**！该选项只需要你的公网服务器 80 端口能正确响应一次企微的 SHA1 验签与 AES 解密握手，即可彻底解锁！

### 3.2 通过接收消息服务器 URL 验证解锁
在云服务器（如阿里云/腾讯云 Linux）上启动临时验证脚本（见项目根目录 `wechat_server.py`）：
```bash
# 1. 安装解密依赖
apt update && apt install -y python3-cryptography

# 2. 启动验证脚本 (监听 80 端口)
python3 wechat_server.py
```

在自建应用页面进入 **“设置 API 接收 / 接收消息服务器”**：
- **URL**: `http://你的域名/wechat`（如已解析到该服务器）
- **Token** 与 **EncodingAESKey**: 点击“随机生成”，填入脚本中保持一致。
- 点击 **“保存 (Save)”**，服务器脚本解密并原样回显 echostr，网页立即提示保存成功！
- 保存成功后，回到应用首页，**“企业可信 IP”输入框立即解锁**，填入你的服务器出口公网 IP 保存即可。

### 3.3 80 端口冲突解决方案
如果云服务器上 80 端口已被 **Nginx / OpenResty / 宝塔面板 / 1Panel** 占用：
1. **方案 A（临时停止法，最快）**：
   ```bash
   systemctl stop openresty   # 暂停 30 秒
   python3 wechat_server.py   # 运行验证并点击企微后台保存
   systemctl start openresty  # 恢复原有网站
   ```
2. **方案 B（反向代理法，长久）**：
   将 Python 服务端口改为 `8088`，在 Nginx/OpenResty 的配置文件 `server { ... }` 中添加：
   ```nginx
   location /wechat {
       proxy_pass http://127.0.0.1:8088;
       proxy_set_header Host $host;
       proxy_set_header X-Real-IP $remote_addr;
   }
   ```
   重载 Nginx 后，企微请求 80 端口无缝转给 Python 服务，两者互不干扰。

---

## 4. Linux 云服务器 Systemd 守护进程运维

将 MailAssist 配置为系统服务，实现服务器开机自启与崩溃自动重连：

### 4.1 服务配置文件 (`/etc/systemd/system/mail_assist.service`)
```ini
[Unit]
Description=MailAssist - Intelligent Email Monitor & WeChat Notifier Agent
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/mail_assist
ExecStart=/root/mail_assist/venv/bin/python run.py
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
```

### 4.2 常用管理命令
```bash
# 重载并启动服务
systemctl daemon-reload
systemctl enable --now mail_assist

# 查看运行状态
systemctl status mail_assist

# 查看实时运行日志 (追踪每封邮件的 LLM 判定与推送)
journalctl -u mail_assist -f

# 重启 / 停止服务
systemctl restart mail_assist
systemctl stop mail_assist
```

---

## 5. 网络与代理路由最佳实践

在国内云服务器（如阿里云）或本地运行多邮箱监听时，各模块网络特性截然不同：

| 服务模块 | 推荐路由策略 | 为什么？ |
| :--- | :--- | :--- |
| **Gmail (`imap.gmail.com:993`)** | **必须走代理** (如 `http://127.0.0.1:18889`) | GFW 阻断导致直连超时挂起。 |
| **QQ 邮箱 / 高校内部邮箱** | **严禁走海外代理** (必须国内直连) | 海外 IP 会触发腾讯/高校安全风控，导致异地冻结。 |
| **企业微信 API (`qyapi.weixin.qq.com`)** | **严禁走海外代理** (必须国内直连) | 若出口 IP 变更为海外节点，会因不在白名单中被企微拒绝。 |
| **arXiv 论文与开源 PDF 下载** | **可选代理加速** | 提升论文抓取与 PDF 下载稳定性。 |
| **LLM 大模型 API** | 国内直连 (国内模型) / 代理 (海外模型) | 按需配置。 |

本项目通过在 `config.yaml` 中提供**细粒度（分邮箱）的独立 `proxy` 字段**，原生解决了上述冲突，各取所需，互不干扰。
