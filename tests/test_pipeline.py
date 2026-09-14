"""集成与单元测试."""

import pytest
import os
import shutil
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
