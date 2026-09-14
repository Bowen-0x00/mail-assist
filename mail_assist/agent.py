"""双轨智能分析 Agent (事务待办评估 + 学术论文阅读筛选)."""

import json
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from loguru import logger
from .config import UserProfile
from .llm_client import LLMClient
from .parser import ParsedEmail
from .scholar import PaperDetail


@dataclass
class TaskAnalysisResult:
    """普通邮件事务分析结果."""
    importance_score: int       # 1-5 分
    urgency: str                # low, medium, high
    action_required: bool       # 是否需要用户处理
    action_summary: str         # 需要用户做的具体动作
    deadline: Optional[str]     # 截止时间
    reason: str                 # 判定理由
    need_notify: bool           # 是否应当推送到微信


@dataclass
class ScholarAnalysisResult:
    """学术论文阅读评估结果."""
    paper_id: str
    title: str
    relevance_score: int        # 0-100 分
    core_contribution: str      # 核心贡献与创新点
    method_highlight: str       # 方法或架构亮点
    relevance_reason: str       # 与用户研究的关联或启发点
    tags: List[str]             # 核心标签
    need_notify: bool           # 是否应当推送到微信
    url: str
    pdf_url: Optional[str]


class TaskAgent:
    """日常与工作邮件事务分析 Agent."""

    def __init__(self, llm_client: LLMClient, min_score_threshold: int = 3):
        self.llm = llm_client
        self.min_score_threshold = min_score_threshold

    def analyze(self, email: ParsedEmail) -> TaskAnalysisResult:
        """分析邮件的重要度、时效性与待办事项."""
        # 1. 尝试大模型分析
        if self.llm.is_configured():
            res = self._analyze_with_llm(email)
            if res:
                return res

        # 2. 启发式规则兜底 (无大模型或大模型超时)
        return self._heuristic_analysis(email)

    def _analyze_with_llm(self, email: ParsedEmail) -> Optional[TaskAnalysisResult]:
        system_prompt = """你是一个顶级的高管与科研学者私人邮件助理。你的职责是帮用户过滤无关邮件，精准识别出【真正需要用户关注、决策或回复】的邮件。

请仔细阅读邮件发件人、主题与正文，按以下标准严格打分评估：
- 1分：纯垃圾、广告、营销推广、无效系统通知（绝不打扰用户）
- 2分：常规订阅、每周新闻快讯、一般知会（无需处理）
- 3分：正常业务沟通、日常工作协作、需要稍后浏览的常规信件
- 4分：重要待办、领导/导师/合作者邮件、会议邀请、账号账单待付款
- 5分：紧急突发事件、临近截止日的催促、涉及权限/安全的重大事务

请输出标准 JSON 格式，字段要求如下：
{
  "importance_score": 1到5的整数,
  "urgency": "low" 或 "medium" 或 "high",
  "action_required": true 或 false,
  "action_summary": "明确需要用户采取的一句话行动指南 (若无则填空字符串)",
  "deadline": "明确提取出的截止时间 (若无则为 null)",
  "reason": "简明扼要的判定理由",
  "need_notify": true 或 false (当 importance_score >= 3 且确实需要用户处理或知晓时为 true)
}"""

        # 截断正文，保留前 3000 字
        truncated_body = email.text_content[:3000] if email.text_content else "[无正文]"
        user_prompt = f"""发件人: {email.sender}
主题: {email.subject}
日期: {email.date_str}
附件列表: {', '.join(email.attachments) if email.attachments else '无'}

邮件正文内容:
{truncated_body}"""

        data = self.llm.chat_json(system_prompt, user_prompt)
        if not data:
            return None

        score = int(data.get("importance_score", 2))
        need_notify = bool(data.get("need_notify", score >= self.min_score_threshold))

        return TaskAnalysisResult(
            importance_score=score,
            urgency=str(data.get("urgency", "low")),
            action_required=bool(data.get("action_required", False)),
            action_summary=str(data.get("action_summary", "")),
            deadline=data.get("deadline"),
            reason=str(data.get("reason", "")),
            need_notify=need_notify
        )

    def _heuristic_analysis(self, email: ParsedEmail) -> TaskAnalysisResult:
        """基于关键词的简单规则分析 (兜底机制)."""
        combined = f"{email.subject} {email.text_content[:500]}".lower()
        urgent_words = ["紧急", "urgent", "asap", "催", "尽快", "逾期", "立即处理"]
        action_words = ["请确认", "请回复", "待审批", "签字", "会议邀请", "deadline", "截止时间", "验证码", "账单"]
        spam_words = ["unsubscribe", "退订", "促销", "双11", "特价", "优惠券", "广告"]

        if any(w in combined for w in spam_words) and not any(w in combined for w in action_words):
            return TaskAnalysisResult(1, "low", False, "", None, "检测为营销广告邮件", False)

        is_urgent = any(w in combined for w in urgent_words)
        has_action = any(w in combined for w in action_words)

        if is_urgent:
            return TaskAnalysisResult(5, "high", True, "邮件包含紧急字样，请及时查阅处理", None, "规则触发：包含高优先级紧急词", True)
        elif has_action:
            return TaskAnalysisResult(4, "medium", True, "邮件包含待办/会议/截止日提醒", None, "规则触发：包含待办操作词", True)

        return TaskAnalysisResult(2, "low", False, "", None, "常规通知，无需即时处理", False)


class ScholarAgent:
    """学术论文深度阅读与画像匹配 Agent."""

    def __init__(self, llm_client: LLMClient, user_profile: UserProfile, score_threshold: int = 65):
        self.llm = llm_client
        self.profile = user_profile
        self.score_threshold = score_threshold

    def evaluate_paper(self, paper: PaperDetail) -> ScholarAnalysisResult:
        """阅读并评估论文相关度与核心亮点."""
        if self.llm.is_configured():
            res = self._evaluate_with_llm(paper)
            if res:
                return res

        return self._heuristic_evaluate(paper)

    def _evaluate_with_llm(self, paper: PaperDetail) -> Optional[ScholarAnalysisResult]:
        topics_desc = "\n".join([f"- {t}" for t in self.profile.research_topics])
        keywords_desc = ", ".join(self.profile.keywords)
        exclude_desc = "\n".join([f"- {e}" for e in self.profile.exclude_topics])

        system_prompt = f"""你是一位敏锐的科研导师与学术助手。请根据用户的研究兴趣画像，评估待选论文的相关度，并生成简短的速读导读卡片。

【用户的核心研究方向】
{topics_desc}

【用户关注的关键词】
{keywords_desc}

【用户希望过滤/排除的方向】
{exclude_desc}

【打分与评估标准】
- 80-100分：与用户的核心方向高度契合，方法或思路对当前课题有直接启发，必读！
- 65-79分：相关领域前沿，存在技术借鉴意义或值得泛读。
- 0-64分：边缘相关或属于排除领域，无需打扰用户。

请输出标准 JSON 格式：
{{
  "relevance_score": 0到100的整数分,
  "core_contribution": "1-2句话精炼提炼论文解决了什么新问题、提出了什么核心贡献",
  "method_highlight": "1句话概括核心技术方法、架构或数学机制",
  "relevance_reason": "说明为什么这篇论文与用户的研究方向相关，对用户有何启发",
  "tags": ["标签1", "标签2"],
  "need_notify": true 或 false (当 relevance_score >= {self.score_threshold} 时为 true)
}}"""

        text_to_read = paper.abstract
        if paper.pdf_snippet:
            text_to_read += f"\n\n【论文正文摘要导读 (Intro/Conclusion)】:\n{paper.pdf_snippet}"

        user_prompt = f"""论文标题: {paper.title}
作者: {', '.join(paper.authors) if paper.authors else '未指定'}
来源: {paper.source}
链接: {paper.url}

论文摘要与导读材料:
{text_to_read[:3500]}"""

        data = self.llm.chat_json(system_prompt, user_prompt)
        if not data:
            return None

        score = int(data.get("relevance_score", 50))
        need_notify = bool(data.get("need_notify", score >= self.score_threshold))

        return ScholarAnalysisResult(
            paper_id=paper.paper_id,
            title=paper.title,
            relevance_score=score,
            core_contribution=str(data.get("core_contribution", "")),
            method_highlight=str(data.get("method_highlight", "")),
            relevance_reason=str(data.get("relevance_reason", "")),
            tags=list(data.get("tags", [])),
            need_notify=need_notify,
            url=paper.url,
            pdf_url=paper.pdf_url
        )

    def _heuristic_evaluate(self, paper: PaperDetail) -> ScholarAnalysisResult:
        """基于关键词交集的启发式匹配兜底."""
        content = f"{paper.title} {paper.abstract}".lower()
        matched_keywords = [kw for kw in self.profile.keywords if kw.lower() in content]
        matched_topics = [tp for tp in self.profile.research_topics if any(k in content for k in tp.lower().split())]

        score = 40
        if matched_topics:
            score += 30
        if matched_keywords:
            score += min(len(matched_keywords) * 10, 30)

        need_notify = score >= self.score_threshold
        return ScholarAnalysisResult(
            paper_id=paper.paper_id,
            title=paper.title,
            relevance_score=score,
            core_contribution=paper.abstract[:150] + "...",
            method_highlight="基于关键词自动匹配",
            relevance_reason=f"匹配到关键词: {', '.join(matched_keywords)}",
            tags=matched_keywords[:3],
            need_notify=need_notify,
            url=paper.url,
            pdf_url=paper.pdf_url
        )
