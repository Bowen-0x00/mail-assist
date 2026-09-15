"""微信交互指令处理器与动态配置热调整模块."""

import re
import yaml
from typing import Dict, Any, Optional, Tuple
from loguru import logger
from .config import is_in_quiet_hours


class CommandHandler:
    """处理用户在微信对话框中输入的控制指令并执行热调参."""

    def __init__(self, service):
        self.service = service

    def handle_command(self, text: str, from_user: str = "@all") -> str:
        """解析并执行微信指令，返回回复文本."""
        cmd = text.strip()
        logger.info(f"[Command] 收到微信控制指令: {cmd}")

        # 1. 帮助指令
        if cmd.lower() in ("/help", "help", "帮助", "?", "？"):
            return self._cmd_help()

        # 2. 状态查询
        if cmd.lower() in ("/status", "status", "状态"):
            return self._cmd_status()

        # 3. 立即检查邮件
        if cmd.lower() in ("/check", "check", "查邮件", "立即检查"):
            return self._cmd_check()

        # 4. 免打扰/夜间休眠时段设置: /quiet 23:00-09:00 或 /quiet off 或 休眠 23:00-09:00
        m_quiet = re.match(r'^(?:/quiet|quiet|/sleep|sleep|休眠)\s*(.+)$', cmd, re.IGNORECASE)
        if m_quiet:
            val = m_quiet.group(1).strip()
            return self._cmd_set_quiet_hours(val)

        # 5. 指定单个邮箱的抓取天数: /days Gmail 3 或 范围 QQ 7
        m_days_spec = re.match(r'^(?:/days|days|范围)\s+([\w\u4e00-\u9fa5]+)\s+(\d+)$', cmd, re.IGNORECASE)
        if m_days_spec:
            box_name = m_days_spec.group(1).strip()
            days = int(m_days_spec.group(2))
            return self._cmd_set_mailbox_days(box_name, days)

        # 6. 全局调整抓取天数范围: /days 3 或 范围 3
        m_days = re.match(r'^(?:/days|days|范围)\s*(\d+)$', cmd, re.IGNORECASE)
        if m_days:
            days = int(m_days.group(1))
            return self._cmd_set_days(days)

        # 7. 调整轮询频率: /interval 60 或 频率 60
        m_interval = re.match(r'^(?:/interval|interval|频率)\s*(\d+)$', cmd, re.IGNORECASE)
        if m_interval:
            interval = int(m_interval.group(1))
            return self._cmd_set_interval(interval)

        # 8. 调整论文阈值: /score 75 或 阈值 75
        m_score = re.match(r'^(?:/score|score|阈值)\s*(\d+)$', cmd, re.IGNORECASE)
        if m_score:
            score = int(m_score.group(1))
            return self._cmd_set_score(score)

        # 9. 添加学术关键词: /addkw 关键词 或 添加关键词 关键词
        m_addkw = re.match(r'^(?:/addkw|addkw|添加关键词)\s*(.+)$', cmd, re.IGNORECASE)
        if m_addkw:
            kw = m_addkw.group(1).strip()
            return self._cmd_add_keyword(kw)

        # 10. 删除学术关键词: /delkw 关键词 或 删除关键词 关键词
        m_delkw = re.match(r'^(?:/delkw|delkw|删除关键词)\s*(.+)$', cmd, re.IGNORECASE)
        if m_delkw:
            kw = m_delkw.group(1).strip()
            return self._cmd_del_keyword(kw)

        # 未识别指令
        return (
            f"❓ 未识别的指令: `{cmd}`\n\n"
            f"输入 `/help` 查看支持的快捷调参指令，如 `/check`、`/quiet 23:00-09:00`、`/days Gmail 3`。"
        )

    def _cmd_help(self) -> str:
        return """📖 **MailAssist 快捷指令手册**
━━━━━━━━━━━━━━━━━━
🔹 **服务与检查**:
- `/check` 或 `查邮件`: 立即触发一次全邮箱检查
- `/status` 或 `状态`: 查看当前配置、免打扰与各邮箱范围

🔹 **免打扰休眠设置 (夜间不打扰)**:
- `/quiet 23:00-09:00`: 设置夜间休眠时段 (在此期间静默不推送)
- `/quiet off`: 关闭免打扰，全天候实时推送

🔹 **抓取范围与频率调参**:
- `/days <天数>`: 全局修改抓取天数 (如 `/days 7`)
- `/days <邮箱名> <天数>`: 单独为指定邮箱设置天数 (如 `/days Gmail 3` 或 `/days QQ 7`)
- `/interval <秒数>`: 修改轮询频率 (如 `/interval 60`)
- `/score <分数>`: 修改学术论文推荐阈值 (如 `/score 75`)

🔹 **研究画像管理**:
- `/addkw <关键词>`: 新增关注关键词
- `/delkw <关键词>`: 移除关注关键词

💡 直接在微信对话框回复以上命令即可实时生效！"""

    def _cmd_status(self) -> str:
        cfg = self.service.cfg
        quiet_status = "休眠静默中 🌙" if is_in_quiet_hours(cfg.app.quiet_hours) else "活跃监控中 🟢"

        # 组装各邮箱状态与抓取范围
        box_lines = []
        for m in cfg.mailboxes:
            status_tag = "✅已启用" if m.enabled else "⚪未启用"
            days_tag = f"最近 {m.since_days} 天" if m.since_days else f"默认 {cfg.app.since_days} 天"
            box_lines.append(f"  • {m.name}: {days_tag} ({status_tag})")
        boxes_text = "\n".join(box_lines) or "无"

        keywords_preview = "、".join(cfg.user_profile.keywords[:6])
        if len(cfg.user_profile.keywords) > 6:
            keywords_preview += f" 等共 {len(cfg.user_profile.keywords)} 个"

        return f"""📊 **MailAssist 当前运行状态**
━━━━━━━━━━━━━━━━━━
🟢 **服务状态**: 24/7 守护运行中
🌙 **免打扰时段**: `{cfg.app.quiet_hours}` ({quiet_status})
⏰ **全局轮询周期**: 每 {cfg.app.poll_interval} 秒 (约 {cfg.app.poll_interval // 60} 分钟)
🎯 **论文推送阈值**: {cfg.app.scholar_score_threshold} 分
🤖 **大模型**: {cfg.llm.model}

📬 **各邮箱监控与检索范围**:
{boxes_text}

🏷️ **核心关键词**: {keywords_preview}"""

    def _cmd_check(self) -> str:
        import threading
        threading.Thread(target=self.service.check_all_mailboxes, daemon=True).start()
        return f"🔍 **已立即触发邮箱检查**\n\n正在后台拉取配置范围内的未读邮件并进行 AI 评估，如有重要事项或高分论文将立即为您推送！"

    def _cmd_set_quiet_hours(self, val: str) -> str:
        clean_val = val.strip()
        if clean_val.lower() in ("off", "none", "false", "0", "关闭"):
            self.service.cfg.app.quiet_hours = "off"
            self._update_yaml_field("config/config.yaml", ["app", "quiet_hours"], "off")
            logger.info("[Command] 免打扰时段已关闭")
            return "✅ **免打扰休眠已关闭**\n\n系统将恢复全天候 24 小时即时推送。"

        # 简单校验格式 HH:MM-HH:MM
        if not re.match(r'^\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}$', clean_val):
            return "⚠️ 格式不正确！请使用 `HH:MM-HH:MM` 格式，例如 `/quiet 23:00-09:00`，或发送 `/quiet off` 关闭。"

        clean_val = re.sub(r'\s+', '', clean_val)
        old_val = self.service.cfg.app.quiet_hours
        self.service.cfg.app.quiet_hours = clean_val
        self._update_yaml_field("config/config.yaml", ["app", "quiet_hours"], clean_val)
        logger.info(f"[Command] 免打扰时段已更新: {old_val} -> {clean_val}")

        return (
            f"🌙 **夜间免打扰休眠时段已生效！**\n\n"
            f"时段: **{clean_val}**\n"
            f"在该时段内系统将静默记录邮件，绝不向您的手机发送任何弹窗提醒，保护您的休息！"
        )

    def _cmd_set_mailbox_days(self, box_name: str, days: int) -> str:
        matched = False
        target_m = None
        for m in self.service.cfg.mailboxes:
            if box_name.lower() in m.name.lower():
                m.since_days = days
                matched = True
                target_m = m
                break

        if not matched:
            valid_names = [m.name for m in self.service.cfg.mailboxes]
            return f"⚠️ 未找到名为 `{box_name}` 的邮箱。当前可用邮箱: {', '.join(valid_names)}"

        # 保存至 config.yaml
        self._update_mailbox_yaml(target_m.name, "since_days", days)
        logger.info(f"[Command] 邮箱 [{target_m.name}] 检索范围已设为: {days} 天")
        return f"✅ **邮箱 [{target_m.name}] 检索范围已更新**\n\n该邮箱将仅检索最近 **{days}** 天内的未读邮件 (已持久化保存)。"

    def _cmd_set_days(self, days: int) -> str:
        old_days = self.service.cfg.app.since_days
        self.service.cfg.app.since_days = days
        self._update_yaml_field("config/config.yaml", ["app", "since_days"], days)
        logger.info(f"[Command] 全局抓取范围已热调整: {old_days}天 -> {days}天")
        return f"✅ **全局抓取时间范围已修改**\n\n默认范围: 最近 **{days}** 天内的未读邮件 (配置已自动持久化保存)。"

    def _cmd_set_interval(self, interval: int) -> str:
        if interval < 10:
            return "⚠️ 轮询周期不能小于 10 秒，以防触发邮件服务商频控限制。"
        old_val = self.service.cfg.app.poll_interval
        self.service.cfg.app.poll_interval = interval
        self._update_yaml_field("config/config.yaml", ["app", "poll_interval"], interval)
        logger.info(f"[Command] 轮询周期已热调整: {old_val}秒 -> {interval}秒")
        return f"✅ **轮询周期已修改**\n\n新周期: 每 **{interval}** 秒检查一次邮箱 (配置已自动持久化保存)。"

    def _cmd_set_score(self, score: int) -> str:
        if not (0 <= score <= 100):
            return "⚠️ 论文评分阈值范围必须在 0 到 100 之间。"
        old_val = self.service.cfg.app.scholar_score_threshold
        self.service.cfg.app.scholar_score_threshold = score
        self.service.scholar_agent.score_threshold = score
        self._update_yaml_field("config/config.yaml", ["app", "scholar_score_threshold"], score)
        logger.info(f"[Command] 论文阈值已热调整: {old_val}分 -> {score}分")
        return f"✅ **学术论文推送阈值已修改**\n\n新阈值: **{score}** 分 (高于此分的论文才会推送到微信)。"

    def _cmd_add_keyword(self, kw: str) -> str:
        if not kw:
            return "⚠️ 关键词不能为空。"
        profile = self.service.cfg.user_profile
        if kw in profile.keywords:
            return f"ℹ️ 关键词 `{kw}` 已在关注列表中。"
        profile.keywords.append(kw)
        self._save_profile_keywords(profile.keywords)
        logger.info(f"[Command] 新增研究关键词: {kw}")
        return f"✅ **成功添加关键词**: `{kw}`\n\n当前关注关键词共 {len(profile.keywords)} 个。"

    def _cmd_del_keyword(self, kw: str) -> str:
        profile = self.service.cfg.user_profile
        if kw not in profile.keywords:
            return f"⚠️ 关键词 `{kw}` 不在现有列表中。"
        profile.keywords.remove(kw)
        self._save_profile_keywords(profile.keywords)
        logger.info(f"[Command] 删除研究关键词: {kw}")
        return f"✅ **成功移除关键词**: `{kw}`\n\n当前关注关键词共 {len(profile.keywords)} 个。"

    def _update_yaml_field(self, file_path: str, keys: list, value: Any):
        """持久化保存更新字段到 YAML 配置文件."""
        import os
        if not os.path.exists(file_path):
            return
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}

            cur = data
            for k in keys[:-1]:
                cur = cur.setdefault(k, {})
            cur[keys[-1]] = value

            with open(file_path, "w", encoding="utf-8") as f:
                yaml.dump(data, f, allow_unicode=True, sort_keys=False)
        except Exception as e:
            logger.error(f"[Command] 持久化更新配置异常 ({file_path}): {e}")

    def _update_mailbox_yaml(self, mailbox_name: str, key: str, value: Any):
        """更新指定邮箱的配置项到 config.yaml."""
        p = "config/config.yaml"
        import os
        if not os.path.exists(p):
            return
        try:
            with open(p, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            for m in data.get("mailboxes", []):
                if m.get("name") == mailbox_name:
                    m[key] = value
                    break
            with open(p, "w", encoding="utf-8") as f:
                yaml.dump(data, f, allow_unicode=True, sort_keys=False)
        except Exception as e:
            logger.error(f"[Command] 更新邮箱配置异常: {e}")

    def _save_profile_keywords(self, keywords: list):
        """持久化保存关键词到 user_profile.yaml."""
        p_path = "config/user_profile.yaml"
        import os
        if not os.path.exists(p_path):
            return
        try:
            with open(p_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            data["keywords"] = keywords
            with open(p_path, "w", encoding="utf-8") as f:
                yaml.dump(data, f, allow_unicode=True, sort_keys=False)
        except Exception as e:
            logger.error(f"[Command] 持久化更新用户画像异常: {e}")
