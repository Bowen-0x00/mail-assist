# MailAssist - 智能多邮箱监控与微信通知 Agent

[中文文档](README.md) | [English Documentation](README_EN.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![LLM: OpenAI_Compatible](https://img.shields.io/badge/LLM-OpenAI--Compatible-green.svg)](https://platform.openai.com/)

**MailAssist** 是一个面向个人学者、工程师与科研工作者的轻量级、私有化智能邮件监控 Agent。
能够同时监听多个邮箱（Gmail、QQ 邮箱、网易 163、高校/企业内部 IMAP 邮箱），借助大语言模型（LLM）实现**待办事务智能过滤打分**与**学术论文（arXiv / Google Scholar）深度速读**，并以双通道消息无缝推送到**个人手机微信**与企业微信客户端。

---

## ✨ 核心特性

- 📬 **多邮箱统一监听**：支持 Gmail、QQ 邮箱、高校及企业 IMAP 邮箱并发轮询，基于 SQLite 实现 `Message-ID` 本地幂等去重。
- ⚡ **分模块代理隔离**：内置细粒度代理控制（如 Gmail 走本地 Clash 代理，国内邮箱与微信通知走原生直连，规避风控）。
- 🧠 **大模型智能事务分析**：自动识别邮件发信意图，评估紧急度（low/medium/high）、提取截止时间（Deadline）与建议行动，对广告营销邮件静默过滤。
- 📚 **学术论文定制研读**：
  - 自动捕获 Google Scholar 提醒与 arXiv 日报。
  - 正文精准抽取 Title 与 Abstract，支持通过 PyMuPDF 自动截取开源 PDF 核心导读（Intro + Conclusion）。
  - 对齐个人学术画像（`user_profile.yaml`），评估匹配度（0-100分），生成核心创新、方法亮点与启发导读卡片。
- 💬 **微信时序双通道推送**：
  - 先推企业微信 Markdown 富文本（企业微信客户端享受极佳排版）。
  - 后推个人微信 Textcard 原生卡片（手机个人微信无需安装企业微信 App，原生卡片完美展示并支持一键打开邮箱/论文）。

---

## 🏗️ 系统架构图

```
[ Gmail (Proxy) ]   [ QQ 邮箱 (Direct) ]   [ 高校/企业邮箱 (Direct) ]
         │                    │                     │
         └─────────────┬──────┴─────────────────────┘
                       ▼
         ┌───────────────────────────┐
         │ 1. 邮件解析与状态去重     │
         │    - MIME RFC822 字节解码 │
         │    - SQLite 幂等去重      │
         └─────────────┬─────────────┘
                       ▼
         ┌───────────────────────────┐
         │ 2. 双轨 LLM 智能分析 Agent│
         │    - 事务邮件: 紧急度/待办 │
         │    - 学术邮件: 论文深度速读│
         └─────────────┬─────────────┘
                       ▼
         ┌───────────────────────────┐
         │ 3. 微信时序双通道推送模块 │
         │    - 企微 Markdown 富文本 │
         │    - 个人微信 Textcard    │
         └───────────────────────────┘
```

---

## 🚀 快速开始

### 1. 克隆项目与安装依赖
```bash
git clone https://github.com/Bowen-0x00/mail-assist.git
cd mail-assist

# 安装依赖
pip install -r requirements.txt
```

### 2. 准备配置文件
复制配置模板：
```bash
cp config/config.example.yaml config/config.yaml
```

编辑 `config/config.yaml` 填入您的凭据：
1. **微信推送通道**：
   - 方式 A（推荐）：免认证企业微信应用（填入 `corp_id`、`agent_id`、`corp_secret`）。
   - 方式 B：PushPlus 个人微信直推（填入 `pushplus_token`）。
2. **大语言模型（LLM）**：
   - 支持 DeepSeek、OpenAI、Kimi、Claude 等兼容接口，填入 `base_url` 与 `api_key`。
3. **邮箱账户**：
   - 开启邮箱的 IMAP 服务，填入用户名与授权码（非邮箱登录密码）。

### 3. 定制您的学术研究画像
打开 `config/user_profile.yaml`，按需修改您关心的研究方向与关键词：
```yaml
research_topics:
  - "计算机体系结构 (Computer Architecture) 与四大顶会 (ISCA, MICRO, HPCA, ASPLOS)"
  - "AI 加速器芯片与大模型硬件加速器"
  - "近存计算与存算一体 (PIM / PNM)"
```

### 4. 运行与验证
```bash
# 1. 验证微信通知通道连通性
python run.py --test-wechat

# 2. 模拟测试重要待办事务识别
python run.py --test-task

# 3. 模拟测试学术论文深度速读
python run.py --test-scholar

# 4. 单次拉取所有配置邮箱并退出
python run.py --once

# 5. 启动 24 小时后台常驻守护监听
python run.py
```

---

## 📂 项目结构

```
mail_assist/
├── config/
│   ├── config.example.yaml  # 核心配置模板 (微信凭据、邮箱、LLM API)
│   └── user_profile.yaml    # 用户学术兴趣画像、关键词配置
├── mail_assist/
│   ├── notifier.py          # 微信时序双通道分发器
│   ├── storage.py           # SQLite 本地去重数据库
│   ├── mail_client.py       # 通用 IMAP 客户端 (支持 SOCKS5 / HTTP 代理)
│   ├── parser.py            # 邮件清洗、HTML 净化、arXiv/Scholar 提取
│   ├── scholar.py           # 学术论文检索与 PyMuPDF 核心导读抽取
│   ├── llm_client.py        # 兼容 OpenAI 格式的大模型客户端
│   ├── agent.py             # TaskAgent (事务分析) + ScholarAgent (论文画像打分)
│   └── service.py           # 业务编排主服务
├── deploy/
│   └── mail_assist.service  # Linux Systemd 守护进程服务配置
├── tests/
│   └── test_pipeline.py     # 自动化测试套件
├── run.py                   # CLI 命令行启动与调试入口
├── requirements.txt         # 依赖清单
└── LICENSE                  # MIT 开源许可证
```

---

## 📄 开源许可证

本项目采用 [MIT License](LICENSE) 许可证。欢迎提交 Issue 与 Pull Request！
