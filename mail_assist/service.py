"""邮件监控与通知核心业务编排服务."""

import time
from typing import List
from loguru import logger

from .config import ConfigManager, MailboxConfig
from .storage import Storage
from .notifier import WeChatNotifier, PushPlusNotifier, BaseNotifier
from .llm_client import LLMClient
from .mail_client import IMAPClient
from .scholar import ScholarFetcher
from .agent import TaskAgent, ScholarAgent, TaskAnalysisResult, ScholarAnalysisResult
from .parser import ParsedEmail, PaperItem


class MailAssistService:
    """系统业务主控制器."""

    def __init__(self, config_manager: ConfigManager):
        self.cfg = config_manager
        self.storage = Storage(self.cfg.app.db_path)
        
        if self.cfg.notify.channel == "pushplus":
            self.notifier = PushPlusNotifier(token=self.cfg.notify.pushplus_token)
        else:
            self.notifier = WeChatNotifier(
                corp_id=self.cfg.notify.corp_id,
                agent_id=self.cfg.notify.agent_id,
                corp_secret=self.cfg.notify.corp_secret,
                default_to_user=self.cfg.notify.to_user
            )

        self.llm = LLMClient(self.cfg.llm)
        self.task_agent = TaskAgent(self.llm, min_score_threshold=self.cfg.app.task_importance_threshold)
        self.scholar_agent = ScholarAgent(
            self.llm,
            self.cfg.user_profile,
            score_threshold=self.cfg.app.scholar_score_threshold
        )
        self.scholar_fetcher = ScholarFetcher(cache_dir=self.cfg.app.cache_dir, proxy=self.cfg.app.proxy)

    def process_email(self, mailbox_name: str, email: ParsedEmail):
        """处理单封邮件的完整生命周期."""
        msg_id = email.message_id
        if self.storage.is_email_processed(msg_id):
            logger.debug(f"[{mailbox_name}] 邮件已处理过，跳过: {msg_id}")
            return

        logger.info(f"[{mailbox_name}] 开始处理新邮件: {email.subject[:40]} (发件人: {email.sender[:30]})")

        # 分流处理：学术推送 vs 日常事务
        if email.is_academic and email.papers:
            self._handle_academic_email(mailbox_name, email)
        else:
            self._handle_task_email(mailbox_name, email)

    def _handle_task_email(self, mailbox_name: str, email: ParsedEmail):
        """处理日常事务/工作/通知邮件."""
        result: TaskAnalysisResult = self.task_agent.analyze(email)
        logger.info(f"[{mailbox_name}] 事务分析完成: 重要度 {result.importance_score}/5, 需通知={result.need_notify}")

        notified = False
        if result.need_notify:
            stars = "⭐" * result.importance_score
            urgency_txt = f"【{result.urgency.upper()}】" if result.urgency in ("high", "medium") else ""
            title = f"🔔 {urgency_txt}{email.subject[:35]}"
            summary = f"来源: {mailbox_name} | 时间: {email.date_str or '刚刚'}"
            
            # 1. 微信原生卡片内容 (HTML 格式)
            details = f"<b>发件人</b>: {email.sender[:45]}<br/>" \
                      f"<b>重要度</b>: {stars} ({result.importance_score}/5)<br/>"
            if result.deadline:
                details += f"⏰ <b>截止时间</b>: {result.deadline}<br/>"
            if result.action_summary:
                details += f"👉 <b>建议行动</b>: {result.action_summary}<br/>"
            details += f"<div class=\"highlight\">理由: {result.reason}</div>"

            # 2. 企微 Markdown 富文本内容 (Markdown 格式)
            deadline_info = f"\n> **⏰ 截止时间**: {result.deadline}" if result.deadline else ""
            action_info = f"\n> **👉 行动建议**: {result.action_summary}" if result.action_summary else ""
            md_content = f"""### 🔔 发现重要邮件待处理 {urgency_txt}
**来源**: {mailbox_name}
**发件人**: {email.sender}
**主　题**: {email.subject}
**重要度**: {stars} ({result.importance_score}/5)
{deadline_info}{action_info}
**判定理由**: {result.reason}
**时间**: {email.date_str or '刚刚'}"""

            mail_url = "https://mail.google.com" if "gmail" in mailbox_name.lower() else "https://mail.qq.com"
            notified = self.notifier.send_dual_notification(
                title=title,
                summary=summary,
                details=details,
                markdown_content=md_content,
                url=mail_url,
                btntxt="打开邮箱"
            )
        # 写入数据库记录去重
        self.storage.record_email(
            message_id=email.message_id,
            mailbox_name=mailbox_name,
            subject=email.subject,
            sender=email.sender,
            date_str=email.date_str,
            category="task",
            importance_score=result.importance_score,
            is_notified=notified,
            summary=result.action_summary or result.reason
        )

    def _handle_academic_email(self, mailbox_name: str, email: ParsedEmail):
        """处理包含学术论文（Scholar / arXiv）的推送邮件."""
        logger.info(f"[{mailbox_name}] 检测到学术论文邮件，包含 {len(email.papers)} 篇待阅论文")
        
        notified_any = False
        # 逐篇获取并阅读评估 (限制每次最多深度评估 5 篇，避免过载)
        for p_item in email.papers[:5]:
            if self.storage.is_paper_processed(p_item.paper_id):
                continue

            # 抓取详情与 PDF 导读
            detail = self.scholar_fetcher.get_paper_detail(
                paper_id=p_item.paper_id,
                title=p_item.title,
                source=p_item.source,
                url=p_item.url,
                pdf_url=p_item.pdf_url,
                snippet=p_item.snippet
            )

            # Agent 智能评估
            res: ScholarAnalysisResult = self.scholar_agent.evaluate_paper(detail)
            logger.info(f"[Paper] 《{res.title[:30]}...》相关度评分: {res.relevance_score} (阈值: {self.cfg.app.scholar_score_threshold})")

            paper_notified = False
            if res.need_notify:
                title = f"📚 论文推荐({res.relevance_score}分): {res.title[:30]}"
                summary = f"匹配度: 🔥 {res.relevance_score}分 | 来源: {detail.source}"
                details = f"<b>💡 核心贡献</b>: {res.core_contribution}<br/>" \
                          f"<b>🛠️ 方法亮点</b>: {res.method_highlight}<br/>" \
                          f"<b>🎯 启发价值</b>: {res.relevance_reason}"
                if res.tags:
                    details += f"<br/><div class=\"gray\">标签: {' '.join(res.tags)}</div>"

                tags_str = " ".join([f"`{t}`" for t in res.tags]) if res.tags else ""
                links = f"[🔗 查看论文]({res.url})"
                if res.pdf_url:
                    links += f" | [📄 下载 PDF]({res.pdf_url})"

                md_content = f"""### 📚 发现高相关学术论文推荐
**论文**: {res.title}
**匹配度**: 🔥 **{res.relevance_score} 分** {tags_str}
> **💡 核心创新**: {res.core_contribution}
> **🛠️ 方法亮点**: {res.method_highlight}
> **🎯 与我启发**: {res.relevance_reason}

{links}"""

                target_url = res.pdf_url or res.url
                paper_notified = self.notifier.send_dual_notification(
                    title=title,
                    summary=summary,
                    details=details,
                    markdown_content=md_content,
                    url=target_url,
                    btntxt="查阅论文"
                )
                if paper_notified:
                    notified_any = True

            self.storage.record_paper(
                paper_id=res.paper_id,
                title=res.title,
                authors=", ".join(detail.authors),
                source=detail.source,
                abstract=detail.abstract,
                url=res.url,
                pdf_url=res.pdf_url or "",
                relevance_score=res.relevance_score,
                is_notified=paper_notified,
                analysis=f"{res.core_contribution} | {res.relevance_reason}"
            )

        # 记录邮件本身
        self.storage.record_email(
            message_id=email.message_id,
            mailbox_name=mailbox_name,
            subject=email.subject,
            sender=email.sender,
            date_str=email.date_str,
            category="scholar",
            importance_score=4 if notified_any else 2,
            is_notified=notified_any,
            summary=f"已阅读分析 {len(email.papers)} 篇论文"
        )

    def check_all_mailboxes(self):
        """遍历所有已启用的邮箱并拉取未读邮件."""
        active_boxes = [m for m in self.cfg.mailboxes if m.enabled]
        if not active_boxes:
            logger.warning("[MailAssist] 当前未启用任何邮箱，请在 config/config.yaml 中将 enabled 改为 true 并配置账号密码")
            return

        for m_cfg in active_boxes:
            logger.info(f"[{m_cfg.name}] 正在检查未读邮件...")
            client = IMAPClient(m_cfg)
            try:
                emails = client.fetch_unseen_emails(max_count=self.cfg.app.max_fetch_emails_per_round)
                for mail in emails:
                    self.process_email(m_cfg.name, mail)
            finally:
                client.disconnect()

    def run_forever(self, interval_seconds: int = 180):
        """主循环调度服务."""
        logger.info(f"[MailAssist] 启动后台监控守护服务 (轮询周期: {interval_seconds} 秒)...")
        while True:
            try:
                self.check_all_mailboxes()
            except Exception as e:
                logger.error(f"[MailAssist] 轮询异常: {e}")
            time.sleep(interval_seconds)
