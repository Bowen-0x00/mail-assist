"""邮件监控与通知核心业务编排服务."""

import time
from typing import List, Optional, Dict, Any
from loguru import logger

from .config import ConfigManager, MailboxConfig
from .storage import Storage
from .notifier import WeChatNotifier, PushPlusNotifier, BaseNotifier
from .llm_client import LLMClient
from .mail_client import IMAPClient
from .scholar import ScholarFetcher
from .agent import TaskAgent, ScholarAgent, TaskAnalysisResult, ScholarAnalysisResult
from .parser import ParsedEmail, PaperItem
from .command_handler import CommandHandler

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
        self.cmd_handler = CommandHandler(self)
        self._start_command_server(port=8087)
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
            from .config import is_in_quiet_hours
            if is_in_quiet_hours(self.cfg.app.quiet_hours):
                logger.info(f"[{mailbox_name}] 当前处于夜间休眠免打扰时段 ({self.cfg.app.quiet_hours})，静默记录不发微信推送: {email.subject[:30]}")
            else:
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
                # 记录数据库以获取唯一编号 ID
                email_id = self.storage.record_email(
                    message_id=email.message_id,
                    mailbox_name=mailbox_name,
                    subject=email.subject,
                    sender=email.sender,
                    date_str=email.date_str,
                    category="task",
                    importance_score=result.importance_score,
                    is_notified=False,
                    summary=result.action_summary or result.reason
                )

                md_content = f"""### 🔔 发现重要邮件待处理 [ID: {email_id}] {urgency_txt}
**来源**: {mailbox_name}
**发件人**: {email.sender}
**主　题**: {email.subject}
**重要度**: {stars} ({result.importance_score}/5)
{deadline_info}{action_info}
**判定理由**: {result.reason}
**时间**: {email.date_str or '刚刚'}

💬 追问提示: 回复 `/llm {email_id} 您的提问` 或 `/llm 您的提问` 展开多轮咨询"""

                mail_url = "https://mail.google.com" if "gmail" in mailbox_name.lower() else "https://mail.qq.com"
                notified = self.notifier.send_dual_notification(
                    title=f"🔔 邮件提醒 [ID:{email_id}]: {email.subject[:25]}",
                    summary=summary,
                    details=details + f"<br/><div class=\"gray\">💬 追问提示: 回复 /llm {email_id} 您的提问</div>",
                    markdown_content=md_content,
                    url=mail_url,
                    btntxt="打开邮箱"
                )
                if notified:
                    with self.storage._get_connection() as conn:
                        conn.execute("UPDATE processed_emails SET is_notified = 1 WHERE message_id = ?", (email.message_id,))
                        conn.commit()
            return
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
                from .config import is_in_quiet_hours
                if is_in_quiet_hours(self.cfg.app.quiet_hours):
                    logger.info(f"[Paper] 当前处于夜间休眠免打扰时段 ({self.cfg.app.quiet_hours})，静默记录不发微信推送: {res.title[:30]}")
                else:
                    # 先记录入库以获得该论文在库中的唯一标识与记录
                    self.storage.record_paper(
                        paper_id=res.paper_id,
                        title=res.title,
                        authors=", ".join(detail.authors),
                        source=detail.source,
                        abstract=detail.abstract,
                        url=res.url,
                        pdf_url=res.pdf_url or "",
                        relevance_score=res.relevance_score,
                        is_notified=False,
                        analysis=f"{res.core_contribution} | {res.relevance_reason}"
                    )

                    paper_ref = res.paper_id[:12]
                    title = f"📚 论文推荐({res.relevance_score}分) [ID:{paper_ref}]: {res.title[:25]}"
                    summary = f"匹配度: 🔥 {res.relevance_score}分 | 来源: {detail.source}"
                    details = f"<b>💡 核心贡献</b>: {res.core_contribution}<br/>" \
                              f"<b>🛠️ 方法亮点</b>: {res.method_highlight}<br/>" \
                              f"<b>🎯 启发价值</b>: {res.relevance_reason}"
                    if res.tags:
                        details += f"<br/><div class=\"gray\">标签: {' '.join(res.tags)}</div>"
                    details += f"<br/><div class=\"gray\">💬 追问提示: 回复 /llm {paper_ref} 您的提问 或 /llm 提问</div>"

                    tags_str = " ".join([f"`{t}`" for t in res.tags]) if res.tags else ""
                    links = f"[🔗 查看论文]({res.url})"
                    if res.pdf_url:
                        links += f" | [📄 下载 PDF]({res.pdf_url})"

                    md_content = f"""### 📚 发现高相关学术论文推荐 [ID: {paper_ref}]
**论文**: {res.title}
**匹配度**: 🔥 **{res.relevance_score} 分** {tags_str}
> **💡 核心创新**: {res.core_contribution}
> **🛠️ 方法亮点**: {res.method_highlight}
> **🎯 与我启发**: {res.relevance_reason}

{links}

💬 追问提示: 回复 `/llm {paper_ref} 您的提问` 或 `/llm 您的提问` 展开深度探讨"""

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
                        with self.storage._get_connection() as conn:
                            conn.execute("UPDATE processed_papers SET is_notified = 1 WHERE paper_id = ?", (res.paper_id,))
                            conn.commit()
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

    def check_all_mailboxes(self, override_since_days: Optional[int] = None):
        """遍历所有已启用的邮箱并拉取未读邮件."""
        active_boxes = [m for m in self.cfg.mailboxes if m.enabled]
        if not active_boxes:
            logger.warning("[MailAssist] 当前未启用任何邮箱，请在 config/config.yaml 中将 enabled 改为 true 并配置账号密码")
            return

        for m_cfg in active_boxes:
            since_days = override_since_days if override_since_days is not None else (
                m_cfg.since_days if m_cfg.since_days is not None else self.cfg.app.since_days
            )
            date_desc = f"最近 {since_days} 天" if since_days else "全量历史"
            logger.info(f"[{m_cfg.name}] 正在检查未读邮件 (检索范围: {date_desc})...")
            client = IMAPClient(m_cfg)
            try:
                emails = client.fetch_unseen_emails(
                    max_count=self.cfg.app.max_fetch_emails_per_round,
                    since_days=since_days
                )
                for mail in emails:
                    self.process_email(m_cfg.name, mail)
            finally:
                client.disconnect()

    def send_startup_message(self):
        """发送服务启动与指令手册通知到微信."""
        active_boxes = [m.name for m in self.cfg.mailboxes if m.enabled]
        title = "🚀 MailAssist 邮件监控服务已就绪"
        summary = f"状态: 正常运行 (24/7 守护) | 活跃邮箱: {', '.join(active_boxes) or '无'}"
        
        details = f"<b>检索范围</b>: 最近 {self.cfg.app.since_days} 天未读邮件<br/>" \
                  f"<b>免打扰时段</b>: {self.cfg.app.quiet_hours} (夜间静默不打扰)<br/>" \
                  f"<b>轮询周期</b>: 每 {self.cfg.app.poll_interval} 秒 (约 {self.cfg.app.poll_interval // 60} 分钟)<br/>" \
                  f"<b>论文阈值</b>: {self.cfg.app.scholar_score_threshold} 分及以上推送<br/>" \
                  f"<b>大模型</b>: {self.cfg.llm.model}<br/>" \
                  f"<div class=\"highlight\">💡 <b>微信快捷指令支持</b>:<br/>" \
                  f"• <code>/check</code> : 立即触发一次邮箱检查<br/>" \
                  f"• <code>/status</code> : 查看当前运行状态与配置<br/>" \
                  f"• <code>/quiet 23:00-09:00</code> : 设置夜间免打扰休眠时段<br/>" \
                  f"• <code>/quiet off</code> : 关闭免打扰，全天候即时推送<br/>" \
                  f"• <code>/days 3</code> : 修改全局抓取天数范围<br/>" \
                  f"• <code>/days Gmail 3</code> : 为单个邮箱单独设置天数<br/>" \
                  f"• <code>/interval 60</code> : 动态修改轮询频率(秒)<br/>" \
                  f"• <code>/score 75</code> : 动态修改论文推荐阈值<br/>" \
                  f"• <code>/help</code> : 查看完整指令手册</div>"

        md_content = f"""### 🚀 MailAssist 邮件监控服务已就绪！
**状态**: 🟢 正常运行中 (24/7 后台守护)
**活跃邮箱**: {', '.join(active_boxes) or '无'}
**检索范围**: 最近 {self.cfg.app.since_days} 天未读邮件
**免打扰时段**: `{self.cfg.app.quiet_hours}` (夜间静默不推送)
**轮询周期**: 每 {self.cfg.app.poll_interval} 秒 (约 {self.cfg.app.poll_interval // 60} 分钟)
**论文阈值**: {self.cfg.app.scholar_score_threshold} 分及以上推送
**大模型**: {self.cfg.llm.model}

> 💡 **微信快捷指令支持**：在此对话框回复以下命令可实时调参：
> - `/check` 或 `查邮件`：立即触发一次邮箱检查
> - `/status` 或 `状态`：查看当前配置与运行状态
> - `/quiet 23:00-09:00`：设置夜间免打扰休眠时段 (在此期间不弹窗)
> - `/quiet off`：关闭免打扰休眠时段
> - `/days <天数>`：动态调整抓取天数 (如 `/days 3` 或 `/days 30`)
> - `/days <邮箱名> <天数>`：单独为指定邮箱设置天数 (如 `/days Gmail 3`)
> - `/interval <秒数>`：动态调整检查频率 (如 `/interval 60`)
> - `/score <分数>`：动态调整论文推荐阈值 (如 `/score 75`)
> - `/help`：获取完整指令手册"""
        self.notifier.send_dual_notification(
            title=title,
            summary=summary,
            details=details,
            markdown_content=md_content,
            url="https://mail.google.com",
            btntxt="进入邮箱"
        )

    def _start_command_server(self, port: int = 8087):
        """在本地监听轻量 HTTP 端口以接收微信回调命令并执行."""
        import threading, json
        from urllib.parse import urlparse, parse_qs
        from http.server import HTTPServer, BaseHTTPRequestHandler

        service_ref = self

        class CmdHTTPHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                parsed = urlparse(self.path)
                params = parse_qs(parsed.query)
                cmd_text = params.get("cmd", [""])[0]
                if cmd_text:
                    reply = service_ref.cmd_handler.handle_command(cmd_text)
                    service_ref.notifier.send_dual_notification(
                        title="⚙️ MailAssist 指令执行结果",
                        summary="来自指令热调参",
                        details=reply.replace("\n", "<br/>"),
                        markdown_content=reply,
                        url="https://mail.google.com",
                        btntxt="查看状态"
                    )
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(reply.encode("utf-8"))
                else:
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"MailAssist Command Server Running")

            def do_POST(self):
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length).decode("utf-8", errors="replace")
                try:
                    data = json.loads(body)
                    cmd_text = data.get("command", "")
                    from_user = data.get("from_user", "@all")
                    reply = service_ref.cmd_handler.handle_command(cmd_text, from_user)
                    service_ref.notifier.send_dual_notification(
                        title="⚙️ MailAssist 指令执行结果",
                        summary="来自微信指令交互",
                        details=reply.replace("\n", "<br/>"),
                        markdown_content=reply,
                        url="https://mail.google.com",
                        btntxt="查看状态"
                    )
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(json.dumps({"code": 0, "reply": reply}, ensure_ascii=False).encode("utf-8"))
                except Exception as e:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(str(e).encode("utf-8"))

            def log_message(self, format, *args):
                pass

        def run_server():
            try:
                httpd = HTTPServer(("127.0.0.1", port), CmdHTTPHandler)
                logger.info(f"[Command] 本地指令交互服务已就绪: http://127.0.0.1:{port}")
                httpd.serve_forever()
            except Exception as e:
                logger.debug(f"[Command] 本地指令服务未启动 (可能已在运行): {e}")

        t = threading.Thread(target=run_server, daemon=True)
        t.start()

    def run_forever(self, interval_seconds: Optional[int] = None):
        """主循环调度服务."""
        # 启动时发送一次就绪通知与快捷指令提示
        try:
            self.send_startup_message()
        except Exception as e:
            logger.warning(f"[MailAssist] 发送启动提示失败: {e}")

        poll_interval = interval_seconds or self.cfg.app.poll_interval
        logger.info(f"[MailAssist] 启动后台监控守护服务 (全局轮询周期: {poll_interval} 秒)...")
        while True:
            try:
                self.check_all_mailboxes()
            except Exception as e:
                logger.error(f"[MailAssist] 轮询异常: {e}")
            time.sleep(poll_interval)
