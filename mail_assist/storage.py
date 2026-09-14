"""SQLite 数据持久化与去重模块."""

import os
import sqlite3
from typing import Optional, Dict, Any
from datetime import datetime
from loguru import logger


class Storage:
    """本地 SQLite 数据库管理，用于邮件处理记录与去重."""

    def __init__(self, db_path: str = "data/mail_assist.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=20.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        """初始化必要的数据表."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            
            # 1. 邮件处理记录表 (Message-ID 唯一约束，确保去重)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS processed_emails (
                message_id TEXT PRIMARY KEY,
                mailbox_name TEXT NOT NULL,
                subject TEXT,
                sender TEXT,
                date_str TEXT,
                category TEXT,             -- 'task', 'scholar', 'normal', 'spam'
                importance_score INTEGER,  -- 1-5 分
                is_notified INTEGER DEFAULT 0,
                summary TEXT,
                processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            # 2. 论文处理记录表 (论文标识唯一约束)
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS processed_papers (
                paper_id TEXT PRIMARY KEY,   -- arXiv ID 或 标题哈希
                title TEXT NOT NULL,
                authors TEXT,
                source TEXT,                -- 'arxiv', 'scholar'
                abstract TEXT,
                url TEXT,
                pdf_url TEXT,
                relevance_score INTEGER,    -- 0-100 分
                is_notified INTEGER DEFAULT 0,
                analysis TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """)

            # 3. 索引优化
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_emails_date ON processed_emails(processed_at)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_papers_score ON processed_papers(relevance_score)")
            conn.commit()
            logger.debug(f"[Storage] SQLite 数据库就绪: {self.db_path}")

    def is_email_processed(self, message_id: str) -> bool:
        """检查邮件是否已被处理过."""
        if not message_id:
            return False
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM processed_emails WHERE message_id = ?", (message_id,))
            return cursor.fetchone() is not None

    def record_email(
        self,
        message_id: str,
        mailbox_name: str,
        subject: str,
        sender: str,
        date_str: str,
        category: str = "normal",
        importance_score: int = 0,
        is_notified: bool = False,
        summary: str = ""
    ):
        """记录已处理的邮件."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT OR REPLACE INTO processed_emails 
            (message_id, mailbox_name, subject, sender, date_str, category, importance_score, is_notified, summary, processed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                message_id,
                mailbox_name,
                subject,
                sender,
                date_str,
                category,
                importance_score,
                1 if is_notified else 0,
                summary,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ))
            conn.commit()

    def is_paper_processed(self, paper_id: str) -> bool:
        """检查论文是否已被评估过."""
        if not paper_id:
            return False
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM processed_papers WHERE paper_id = ?", (paper_id,))
            return cursor.fetchone() is not None

    def record_paper(
        self,
        paper_id: str,
        title: str,
        authors: str,
        source: str,
        abstract: str,
        url: str,
        pdf_url: str,
        relevance_score: int,
        is_notified: bool,
        analysis: str
    ):
        """记录论文及其评估结果."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT OR REPLACE INTO processed_papers
            (paper_id, title, authors, source, abstract, url, pdf_url, relevance_score, is_notified, analysis, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                paper_id,
                title,
                authors,
                source,
                abstract,
                url,
                pdf_url,
                relevance_score,
                1 if is_notified else 0,
                analysis,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            ))
            conn.commit()
