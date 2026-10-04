"""集成与单元测试."""

import pytest
import os
import sys
import shutil
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from mail_assist.config import ConfigManager
from mail_assist.storage import Storage
from mail_assist.parser import EmailParser
from mail_assist.scholar import ScholarFetcher
from mail_assist.agent import TaskAgent, ScholarAgent
from mail_assist.llm_client import LLMClient


@pytest.fixture
def temp_env(tmp_path):
    db_file = str(tmp_path / "test.db")
    cache_dir = str(tmp_path / "cache")
    storage = Storage(db_file)
    return storage, cache_dir


def test_storage_deduplication(temp_env):
    storage, _ = temp_env
    msg_id = "test_unique_id_123"
    assert not storage.is_email_processed(msg_id)

    storage.record_email(
        message_id=msg_id,
        mailbox_name="test_box",
        subject="测试邮件",
        sender="sender@test.com",
        date_str="2026-09-14",
        category="task",
        importance_score=4,
        is_notified=True,
        summary="待处理"
    )

    assert storage.is_email_processed(msg_id)


def test_email_parser_normal():
    raw_email = """From: boss@company.com
To: user@company.com
Subject: =?utf-8?B?6YeN6KaB77ya5Lq65LqL5LyR5YGl5LyR5oGv5Yeg5aSp?=
Date: Mon, 14 Sep 2026 10:00:00 +0800
Message-ID: <msg_001@company.com>
Content-Type: text/plain; charset="utf-8"

请于本周五前完成系统人事审批，并回复确认。
""".encode("utf-8")

    parsed = EmailParser.parse_raw_email(raw_email)
    assert parsed.message_id == "msg_001@company.com"
    assert "重要" in parsed.subject
    assert "boss@company.com" in parsed.sender
    assert "人事审批" in parsed.text_content
    assert not parsed.is_academic


def test_email_parser_academic():
    raw_email = """From: no-reply@arxiv.org
To: user@company.com
Subject: cs.AI daily updates
Date: Mon, 14 Sep 2026 10:00:00 +0800
Message-ID: <arxiv_daily_001@arxiv.org>
Content-Type: text/plain; charset="utf-8"

Title: Large Language Models as Tool Users
arXiv:2403.12345
Authors: John Doe, Jane Smith
""".encode("utf-8")

    parsed = EmailParser.parse_raw_email(raw_email)
    assert parsed.is_academic
    assert len(parsed.papers) >= 1
    assert "2403.12345" in parsed.papers[0].paper_id


def test_task_agent_heuristic():
    cfg = ConfigManager()
    llm = LLMClient(cfg.llm)
    agent = TaskAgent(llm, min_score_threshold=3)

    raw_urgent = """From: alert@system.com
Subject: =?utf-8?B?44CQ57Sn5oCl44CR5pyN5Yqh5Zmo5Y+R55Sf5pWF6Zqc77yM6K+356uL5Y2z5aSE55CG?=
Date: Mon, 14 Sep 2026 10:00:00 +0800

服务器CPU持续100%，请立即处理！
""".encode("utf-8")

    parsed = EmailParser.parse_raw_email(raw_urgent)
    result = agent.analyze(parsed)
    assert result.importance_score >= 4
    assert result.need_notify


def test_email_parser_google_scholar_alert():
    """测试 Google Scholar Alert 邮件解析：精准提取具体论文，杜绝抓取学者主页与退订链接."""
    raw_html_email = """From: Google Scholar Alerts <scholaralerts-noreply@google.com>
To: user@example.com
Subject: Yakun Sophia Shao - new articles
Date: Sun, 04 Oct 2026 14:34:00 +0800
Message-ID: <scholar_alert_test_001@google.com>
MIME-Version: 1.0
Content-Type: text/html; charset="utf-8"

<html>
<body>
  <div>
    <h3>
      <a href="https://scholar.google.com/scholar_url?url=https://arxiv.org/pdf/2609.39131&hl=zh-CN&sa=X">[PDF]</a>
      <a href="https://scholar.google.com/scholar_url?url=https://arxiv.org/abs/2609.39131&hl=zh-CN&sa=X">Characterizing High Bandwidth Flash for LLM Serving</a>
    </h3>
    <div style="color: #006621;">Z Yu, C Wong, C Hooper, M Lee, W Kang, Y Cho... - arXiv preprint arXiv ..., 2026</div>
    <div>Large language model (LLM) serving requires substantial memory to store model weights and KV caches...</div>
    <br/>
    <div class="gsc_al_footer">
      This message was sent by Google Scholar because you're following new articles written by <a href="https://scholar.google.com/citations?user=ABCD1234efgh&hl=en">Yakun Sophia Shao</a>.
      <br/>
      <a href="https://scholar.google.com/scholar_alerts?view_op=list_alerts&hl=en">LIST ALERTS</a>
      <a href="https://scholar.google.com/scholar_alerts?view_op=cancel_alert&hl=en">CANCEL ALERT</a>
    </div>
  </div>
</body>
</html>
""".encode("utf-8")

    parsed = EmailParser.parse_raw_email(raw_html_email)
    assert parsed.is_academic
    # 核心断言 1：只能提取出具体的论文，绝对不能把底部学者主页与系统链接误当成论文！
    assert len(parsed.papers) == 1
    
    paper = parsed.papers[0]
    # 核心断言 2：标题干净，去除了 [PDF] 标记
    assert paper.title == "Characterizing High Bandwidth Flash for LLM Serving"
    # 核心断言 3：正确识别出 arXiv ID 并反解真实 URL
    assert "2609.39131" in paper.paper_id
    assert "https://arxiv.org/abs/2609.39131" in paper.url
    assert "https://arxiv.org/pdf/2609.39131" in paper.pdf_url
    # 核心断言 4：正确提取出作者与摘要
    assert "Z Yu" in paper.authors
    assert "Large language model" in paper.snippet
    # 核心断言 5：确保绝无以 Yakun Sophia Shao 命名的条目
    assert not any("Yakun" in p.title for p in parsed.papers)


def test_scholar_agent_profile_guard():
    """测试 ScholarAgent 对学者主页链接的安全拦截."""
    from mail_assist.config import UserProfile
    from mail_assist.scholar import PaperDetail
    
    cfg = ConfigManager()
    llm = LLMClient(cfg.llm)
    profile = UserProfile(
        research_topics=["计算机体系结构", "AI 加速器"],
        keywords=["Gemmini", "RISC-V", "Architecture"],
        exclude_topics=[]
    )
    agent = ScholarAgent(llm, profile, score_threshold=65)
    
    # 构造一个被误传为学者主页的 PaperDetail
    fake_profile_paper = PaperDetail(
        paper_id="scholar_b99e9ef816006be6",
        title="Yakun Sophia Shao",
        authors=[],
        source="scholar",
        abstract="",
        url="https://scholar.google.com/citations?user=ABCD1234efgh&hl=en"
    )
    
    res = agent.evaluate_paper(fake_profile_paper)
    # 必须打低分，且绝不推送
    assert res.relevance_score <= 15
    assert not res.need_notify
    assert "学者" in res.core_contribution or "拦截" in res.core_contribution
