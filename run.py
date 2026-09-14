"""MailAssist 运行入口脚本."""

import argparse
import sys
from loguru import logger

from mail_assist.config import ConfigManager
from mail_assist.service import MailAssistService
from mail_assist.parser import ParsedEmail, PaperItem
from mail_assist.scholar import PaperDetail


def test_wechat_push(service: MailAssistService):
    """测试企业微信通知通道."""
    logger.info("=== 测试企业微信通知通道 ===")
    title = "🚀 MailAssist 邮件助手测试成功"
    summary = "微信双通道通知已打通！"
    details = "<b>系统状态</b>: 正常运行<br/>" \
              "<b>当前模式</b>: 先发企微 Markdown，后发个人微信原生卡片<br/>" \
              "<b>学术画像</b>: 计算机体系结构、AI加速器、CXL近存、RISC-V<br/>" \
              "<div class=\"highlight\">个人微信可直接查阅此卡片，企微可查看完整Markdown排版！</div>"

    md_content = """### 🚀 MailAssist 邮件助手双通道测试成功
**状态**: 微信双通道通知已打通！
**当前学术画像**: 
* 计算机体系结构 (ISCA/MICRO/HPCA/ASPLOS)
* AI 加速器芯片、大模型加速器与 Chiplet
* 近存与存算 (PIM/PNM)、CXL 近存、I/O 复杂度
* RISC-V 处理器、向量扩展与 AI 编译器
> 💡 企业微信展示完整 Markdown 排版，个人微信展示紧凑原生卡片！"""

    ok = service.notifier.send_dual_notification(
        title=title,
        summary=summary,
        details=details,
        markdown_content=md_content,
        url="https://github.com",
        btntxt="进入系统"
    )
    if ok:
        logger.success("企业微信与个人微信双通道测试消息已发送！请查看您的微信。")
    else:
        logger.error("企业微信测试消息发送失败，请检查上面输出的错误提示。")


def test_scholar_agent(service: MailAssistService):
    """测试学术论文分析 Agent (模拟一篇 arXiv 论文)."""
    logger.info("=== 测试学术论文 Agent 研读与推荐 ===")
    # 模拟一篇经典 Agent 论文 ReAct
    fake_paper = PaperDetail(
        paper_id="arxiv_2405.99999",
        title="CXL-PIM: A High-Throughput Near-Memory Computing Accelerator for Generative LLMs",
        authors=["Alex Chen", "David Patterson", "Onur Mutlu"],
        source="arxiv",
        abstract="Large language model (LLM) inference suffers from severe memory-wall bottlenecks and high I/O complexity due to autoregressive decoding and KV cache movement. In this paper, we propose CXL-PIM, an innovative near-memory computing architecture coupled with CXL.mem protocol. We design a specialized vector processing unit integrated inside CXL memory controllers to offload attention GEMV kernels, significantly reducing host-device I/O traffic by 4.8x and achieving 3.2x speedup compared to standard GPU baselines.",
        url="https://arxiv.org/abs/2405.99999",
        pdf_url="https://arxiv.org/pdf/2405.99999.pdf"
    )
    res = service.scholar_agent.evaluate_paper(fake_paper)
    logger.info(f"论文评分结果: 相关度={res.relevance_score}, 需通知={res.need_notify}")
    logger.info(f"核心贡献: {res.core_contribution}")
    logger.info(f"与我启发: {res.relevance_reason}")

    fake_email = ParsedEmail(
        message_id="test_scholar_email_001",
        subject="arXiv.org daily alert: cs.AI update",
        sender="no-reply@arxiv.org",
        date_str="Mon, 14 Sep 2026 08:00:00 +0800",
        text_content="ReAct: Synergizing Reasoning and Acting in Language Models",
        html_content="",
        is_academic=True,
        papers=[PaperItem(
            title=fake_paper.title,
            paper_id=fake_paper.paper_id,
            source="arxiv",
            url=fake_paper.url,
            pdf_url=fake_paper.pdf_url
        )]
    )
    service._handle_academic_email("模拟学术推送", fake_email)


def test_task_agent(service: MailAssistService):
    """测试重要邮件事务识别 Agent (模拟紧急通知)."""
    logger.info("=== 测试重要事务邮件识别 ===")
    fake_email = ParsedEmail(
        message_id="test_task_email_001",
        subject="【紧急待办】关于 2026 年度重点研发项目中期答辩时间调整及材料提交确认",
        sender="科技处科研管理办公室 <project-office@university.edu.cn>",
        date_str="Mon, 14 Sep 2026 09:30:00 +0800",
        text_content="""各位项目负责人：
根据最新科技部通知，中期检查答辩时间提前至本周五上午9:00。
请各课题负责人务必于今日 (9月14日) 18:00 前将最新版 PPT 及财务审计自查表上传至申报系统，并回复本邮件确认参会答辩人员名单。逾期系统将自动关闭，请务必重视！
联系人：李老师 010-88888888""",
        html_content=""
    )

    service.process_email("模拟工作邮箱", fake_email)


def main():
    parser = argparse.ArgumentParser(description="MailAssist - 智能邮件监控与微信通知 Agent")
    parser.add_argument("--test-wechat", action="store_true", help="测试企业微信连通性与发送通知")
    parser.add_argument("--test-scholar", action="store_true", help="模拟测试学术论文研读与通知")
    parser.add_argument("--test-task", action="store_true", help="模拟测试重要待办事务识别与通知")
    parser.add_argument("--once", action="store_true", help="单次运行：检查所有配置邮箱后退出")
    parser.add_argument("--interval", type=int, default=None, help="轮询周期间隔 (秒，默认读取配置 poll_interval)")
    parser.add_argument("--since-days", type=int, default=None, help="覆盖抓取时间范围 (天，默认读取配置 since_days: 7)")
    args = parser.parse_args()

    cfg = ConfigManager()
    service = MailAssistService(cfg)

    if args.test_wechat:
        test_wechat_push(service)
        return

    if args.test_scholar:
        test_scholar_agent(service)
        return

    if args.test_task:
        test_task_agent(service)
        return

    if args.once:
        logger.info("执行单次邮件检查...")
        service.check_all_mailboxes(override_since_days=args.since_days)
        logger.info("单次检查完成")
        return

    service.run_forever(interval_seconds=args.interval)


if __name__ == "__main__":
    main()
