# MailAssist - Intelligent Multi-Mailbox Monitoring & WeChat Notification Agent

[English Documentation](README_EN.md) | [中文文档](README.md)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python: 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![LLM: OpenAI_Compatible](https://img.shields.io/badge/LLM-OpenAI--Compatible-green.svg)](https://platform.openai.com/)

**MailAssist** is a lightweight, private, and AI-powered mailbox monitoring agent designed for researchers, developers, and engineers.
It simultaneously listens to multiple email accounts (Gmail, QQ Mail, 163 Mail, and institutional/university IMAP accounts), leveraging Large Language Models (LLMs) to **intelligently score and filter actionable tasks** and **deeply read/evaluate academic alerts (arXiv & Google Scholar)**, instantly pushing dual-channel notifications directly to your **Personal WeChat** and Enterprise WeChat clients.

> 📖 **Step-by-Step SOP Guide**: See [Full Setup & Operations Guide (docs/SOP_SETUP_GUIDE.md)](docs/SOP_SETUP_GUIDE.md) for detailed walk-throughs on email app passwords, free WeCom setup, IP whitelist unlocking, port 80 reverse proxying, and granular proxy routing.

---

## ✨ Key Features

- 📬 **Unified Multi-Mailbox Listening**: Concurrently polls Gmail, QQ Mail, and enterprise/university IMAP accounts with SQLite-backed `Message-ID` deduplication.
- ⚡ **Granular Proxy Isolation**: Per-mailbox proxy routing (e.g., route Gmail via a local Clash/SOCKS5 proxy, while domestic mailboxes and WeChat APIs stay on direct connections to prevent security flags).
- 🧠 **AI-Powered Task Analysis**: Analyzes sender intent, evaluates urgency (`low`/`medium`/`high`), extracts deadlines, and generates actionable advice while muting promotional/marketing spam.
- 📚 **Tailored Academic Paper Reading**:
  - Automatically captures Google Scholar alerts and arXiv daily updates.
  - Extracts paper titles and abstracts directly from email feeds, with optional PyMuPDF-based extraction of key sections (Introduction & Conclusion) from open-access PDFs.
  - Compares papers against your research profile (`user_profile.yaml`), scoring relevance (0-100) and generating core innovations, methodology highlights, and inspirational takeaways.
- 💬 **Sequential Dual-Channel WeChat Push**:
  - Pushes **Markdown rich-text** first (for optimal formatting on Enterprise WeChat desktop/mobile clients).
  - Pushes native **Textcard cards** second (renders natively in Personal WeChat with clickable buttons, without requiring the Enterprise WeChat app).

---

## 🏗️ Architecture

```
[ Gmail (Proxy) ]   [ QQ Mail (Direct) ]   [ Edu/Company Mail (Direct) ]
         │                    │                          │
         └─────────────┬──────┴──────────────────────────┘
                       ▼
         ┌───────────────────────────┐
         │ 1. Email Parser & Storage │
         │    - MIME RFC822 Decoding │
         │    - SQLite Deduplication │
         └─────────────┬─────────────┘
                       ▼
         ┌───────────────────────────┐
         │ 2. Dual-Track LLM Agent   │
         │    - Tasks: Urgency & Todo│
         │    - Papers: Deep Reading │
         └─────────────┬─────────────┘
                       ▼
         ┌───────────────────────────┐
         │ 3. Dual-Channel WeCom Push│
         │    - Markdown Rich Text   │
         │    - Native WeChat Card   │
         └───────────────────────────┘
```

---

## 🚀 Quick Start

### 1. Clone & Install Dependencies
```bash
git clone https://github.com/Bowen-0x00/mail-assist.git
cd mail-assist

pip install -r requirements.txt
```

### 2. Configure Credentials
Copy the example configuration:
```bash
cp config/config.example.yaml config/config.yaml
```

Edit `config/config.yaml`:
1. **WeChat Channel**:
   - Option A (Recommended): Enterprise WeChat self-built app (fill in `corp_id`, `agent_id`, `corp_secret`).
   - Option B: PushPlus direct personal push (fill in `pushplus_token`).
2. **LLM Provider**:
   - Supports any OpenAI-compatible API (DeepSeek, OpenAI, Kimi, Claude, etc.). Fill in `base_url` and `api_key`.
3. **Mailboxes**:
   - Enable IMAP on your email provider and fill in your username and authorization code / app password.

### 3. Customize Your Research Profile
Edit `config/user_profile.yaml` to define your target research fields and keywords:
```yaml
research_topics:
  - "Computer Architecture and top-tier conferences (ISCA, MICRO, HPCA, ASPLOS)"
  - "AI Accelerator Chips & LLM Hardware Accelerators"
  - "Near-Memory Computing and Processing-in-Memory (PIM / PNM)"
```

### 4. Run & Verify
```bash
# 1. Test WeChat push channel
python run.py --test-wechat

# 2. Simulate task email evaluation
python run.py --test-task

# 3. Simulate academic paper reading
python run.py --test-scholar

# 4. Run a single poll and exit
python run.py --once

# 5. Start continuous daemon
python run.py
```

---

## 📂 Project Structure

```
mail_assist/
├── config/
│   ├── config.example.yaml  # Configuration template
│   └── user_profile.yaml    # Academic interest profile & keywords
├── mail_assist/
│   ├── notifier.py          # Sequential dual-channel WeChat notifier
│   ├── storage.py           # SQLite deduplication storage
│   ├── mail_client.py       # Universal IMAP client (supports HTTP/SOCKS5 proxy)
│   ├── parser.py            # Email parsing & sanitization
│   ├── scholar.py           # Paper fetching & PyMuPDF PDF extraction
│   ├── llm_client.py        # OpenAI-compatible LLM client
│   ├── agent.py             # TaskAgent & ScholarAgent
│   └── service.py           # Main orchestration service
├── deploy/
│   └── mail_assist.service  # Linux Systemd service unit
├── tests/
│   └── test_pipeline.py     # Automated test suite
├── run.py                   # CLI entrypoint
├── requirements.txt         # Dependencies
└── LICENSE                  # MIT License
```

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
