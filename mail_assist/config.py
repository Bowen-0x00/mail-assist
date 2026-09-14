"""配置管理模块."""

import os
import yaml
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from loguru import logger


@dataclass
class MailboxConfig:
    name: str
    type: str
    host: str
    port: int
    ssl: bool
    username: str
    password: str
    check_interval: int = 180
    enabled: bool = True
    proxy: Optional[str] = None
    since_days: Optional[int] = None

@dataclass
class NotifyConfig:
    channel: str = "wechat"               # "pushplus" 或 "wechat"
    pushplus_token: str = ""
    corp_id: str = ""
    agent_id: int = 0
    corp_secret: str = ""
    to_user: str = "@all"

@dataclass
class LLMConfig:
    base_url: str
    api_key: str
    model: str = "deepseek-chat"
    temperature: float = 0.2


@dataclass
class AppConfig:
    db_path: str = "data/mail_assist.db"
    cache_dir: str = "data/cache"
    max_fetch_emails_per_round: int = 10
    scholar_score_threshold: int = 65
    task_importance_threshold: int = 3
    proxy: Optional[str] = None
    since_days: int = 7
    poll_interval: int = 180

@dataclass
class UserProfile:
    research_topics: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    exclude_topics: List[str] = field(default_factory=list)
    focus_authors: List[str] = field(default_factory=list)
    summary_preferences: Dict[str, Any] = field(default_factory=dict)


class ConfigManager:
    """系统配置统一载入器."""

    def __init__(self, config_path: str = "config/config.yaml", profile_path: str = "config/user_profile.yaml"):
        self.config_path = config_path
        self.profile_path = profile_path
        self.notify: Optional[NotifyConfig] = None
        self.wechat: Optional[NotifyConfig] = None
        self.llm: Optional[LLMConfig] = None
        self.mailboxes: List[MailboxConfig] = []
        self.app: AppConfig = AppConfig()
        self.user_profile: UserProfile = UserProfile()
        self.load()

    def load(self):
        """载入配置文件."""
        if not os.path.exists(self.config_path):
            if os.path.exists("config/config.example.yaml"):
                self.config_path = "config/config.example.yaml"
            else:
                raise FileNotFoundError(f"主配置文件不存在: {self.config_path}")

        with open(self.config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        # 1. 微信与推送通道配置
        nc = raw.get("notify", raw.get("wechat", {}))
        self.notify = NotifyConfig(
            channel=str(nc.get("channel", "wechat")),
            pushplus_token=str(nc.get("pushplus_token", "")),
            corp_id=str(nc.get("corp_id", "")),
            agent_id=int(nc.get("agent_id", 0)),
            corp_secret=str(nc.get("corp_secret", "")),
            to_user=str(nc.get("to_user", "@all"))
        )
        self.wechat = self.notify

        # 2. LLM 配置
        lc = raw.get("llm", {})
        self.llm = LLMConfig(
            base_url=str(lc.get("base_url", "https://api.deepseek.com/v1")),
            api_key=str(lc.get("api_key", "")),
            model=str(lc.get("model", "deepseek-chat")),
            temperature=float(lc.get("temperature", 0.2))
        )

        # 3. 邮箱列表
        self.mailboxes = []
        for m in raw.get("mailboxes", []):
            self.mailboxes.append(MailboxConfig(
                name=m.get("name", "未命名邮箱"),
                type=m.get("type", "imap"),
                host=m.get("host", ""),
                port=int(m.get("port", 993)),
                ssl=bool(m.get("ssl", True)),
                username=m.get("username", ""),
                password=m.get("password", ""),
                check_interval=int(m.get("check_interval", 180)),
                enabled=bool(m.get("enabled", False)),
                proxy=m.get("proxy"),
                since_days=int(m["since_days"]) if m.get("since_days") is not None else None
            ))
        # 4. App 参数
        ac = raw.get("app", {})
        self.app = AppConfig(
            db_path=ac.get("db_path", "data/mail_assist.db"),
            cache_dir=ac.get("cache_dir", "data/cache"),
            max_fetch_emails_per_round=int(ac.get("max_fetch_emails_per_round", 10)),
            scholar_score_threshold=int(ac.get("scholar_score_threshold", 65)),
            task_importance_threshold=int(ac.get("task_importance_threshold", 3)),
            proxy=ac.get("proxy"),
            since_days=int(ac.get("since_days", 7)) if ac.get("since_days") is not None else 7,
            poll_interval=int(ac.get("poll_interval", 180))
        )
        # 5. 用户画像
        if os.path.exists(self.profile_path):
            with open(self.profile_path, "r", encoding="utf-8") as f:
                p_raw = yaml.safe_load(f) or {}
            self.user_profile = UserProfile(
                research_topics=p_raw.get("research_topics", []),
                keywords=p_raw.get("keywords", []),
                exclude_topics=p_raw.get("exclude_topics", []),
                focus_authors=p_raw.get("focus_authors", []),
                summary_preferences=p_raw.get("summary_preferences", {})
            )
        logger.info(f"[Config] 配置成功载入：{len(self.mailboxes)} 个邮箱配置 (启用: {sum(1 for m in self.mailboxes if m.enabled)})")
