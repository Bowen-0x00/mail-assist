"""微信通知通道模块 (支持免认证企业微信应用 与 PushPlus 个人微信直推)."""

import time
import requests
from typing import Optional, Dict, Any
from loguru import logger


class BaseNotifier:
    """通知器基类."""

    def send_dual_notification(
        self,
        title: str,
        summary: str,
        details: str,
        markdown_content: str,
        url: Optional[str] = None,
        btntxt: str = "查看详情"
    ) -> bool:
        raise NotImplementedError

    def send_notification(
        self,
        title: str,
        summary: str,
        details: str,
        url: Optional[str] = None,
        btntxt: str = "查看详情"
    ) -> bool:
        raise NotImplementedError

    def send_markdown(self, content: str, title: Optional[str] = None) -> bool:
        raise NotImplementedError


class PushPlusNotifier(BaseNotifier):
    """PushPlus (推送加) 个人微信直推器."""

    def __init__(self, token: str):
        self.token = token.strip()

    def send_dual_notification(
        self,
        title: str,
        summary: str,
        details: str,
        markdown_content: str,
        url: Optional[str] = None,
        btntxt: str = "查看详情"
    ) -> bool:
        return self.send_markdown(markdown_content, title)

    def send_notification(
        self,
        title: str,
        summary: str,
        details: str,
        url: Optional[str] = None,
        btntxt: str = "查看详情"
    ) -> bool:
        content = f"### {title}\n\n{summary}\n\n{details}"
        if url:
            content += f"\n\n[{btntxt}]({url})"
        return self.send_markdown(content, title)

    def send_markdown(self, content: str, title: Optional[str] = None) -> bool:
        if not self.token or self.token == "YOUR_PUSHPLUS_TOKEN":
            logger.error("[PushPlus] 未配置有效的 pushplus token")
            return False

        msg_title = title or "邮件助手通知"
        url = "http://www.pushplus.plus/send"
        payload = {
            "token": self.token,
            "title": msg_title,
            "content": content,
            "template": "markdown",
            "channel": "wechat"
        }

        try:
            resp = requests.post(url, json=payload, timeout=10)
            data = resp.json()
            if data.get("code") == 200:
                logger.info(f"[PushPlus] 微信通知推送成功 -> {msg_title}")
                return True
            else:
                logger.error(f"[PushPlus] 推送失败: {data.get('msg')}")
                return False
        except Exception as e:
            logger.error(f"[PushPlus] 推送网络请求异常: {e}")
            return False


class WeChatNotifier(BaseNotifier):
    """企业微信应用消息推送器 (支持双发：先 Markdown 供企微，后 Textcard 供个人微信)."""

    def __init__(self, corp_id: str, agent_id: int, corp_secret: str, default_to_user: str = "@all"):
        self.corp_id = corp_id.strip()
        self.agent_id = int(agent_id) if agent_id else 0
        self.corp_secret = corp_secret.strip()
        self.default_to_user = default_to_user.strip() or "@all"
        
        self._access_token: Optional[str] = None
        self._token_expires_at: float = 0.0

    def get_access_token(self, force_refresh: bool = False) -> str:
        """获取企业微信 access_token，带本地过期缓存."""
        now = time.time()
        if not force_refresh and self._access_token and now < self._token_expires_at:
            return self._access_token

        url = "https://qyapi.weixin.qq.com/cgi-bin/gettoken"
        params = {
            "corpid": self.corp_id,
            "corpsecret": self.corp_secret
        }

        try:
            resp = requests.get(url, params=params, timeout=10)
            data = resp.json()
        except Exception as e:
            logger.error(f"[WeChat] 获取 access_token 网络异常: {e}")
            raise

        if data.get("errcode") != 0:
            err_msg = data.get("errmsg", "未知错误")
            err_code = data.get("errcode")
            logger.error(f"[WeChat] 获取 access_token 失败 [code {err_code}]: {err_msg}")
            raise RuntimeError(f"获取微信 Token 失败: {err_msg} (代码: {err_code})")

        self._access_token = data["access_token"]
        self._token_expires_at = now + data.get("expires_in", 7200) - 300
        logger.debug("[WeChat] access_token 获取并缓存成功")
        return self._access_token

    def send_dual_notification(
        self,
        title: str,
        summary: str,
        details: str,
        markdown_content: str,
        url: Optional[str] = None,
        btntxt: str = "查看详情"
    ) -> bool:
        """先发送 Markdown 富文本（企业微信端享受极佳排版），再发送 textcard（个人微信端原生无缝展示）."""
        logger.info("[WeChat] 正在双通道推送 (1. 企微Markdown富文本 -> 2. 个人微信原生卡片)...")
        # 1. 先发 markdown 给企业微信端
        ok_md = self.send_markdown(markdown_content)
        # 停顿 0.6 秒确保时序
        time.sleep(0.6)
        # 2. 后发 textcard 原生卡片给个人微信端
        ok_card = self.send_notification(title=title, summary=summary, details=details, url=url, btntxt=btntxt)
        return ok_md or ok_card

    def send_notification(
        self,
        title: str,
        summary: str,
        details: str,
        url: Optional[str] = None,
        btntxt: str = "查看详情"
    ) -> bool:
        """发送卡片通知，个人微信插件完美原生支持展现."""
        target_url = url or "https://mail.google.com"
        description = f"<div class=\"gray\">{summary}</div><div class=\"normal\">{details}</div>"
        return self.send_card(title=title, description=description, url=target_url, btntxt=btntxt)

    def send_card(self, title: str, description: str, url: str, btntxt: str = "查看详情", to_user: Optional[str] = None) -> bool:
        """发送文本卡片消息 (textcard，个人微信端原生完整支持)."""
        payload = {
            "title": title[:120],
            "description": description[:500],
            "url": url,
            "btntxt": btntxt[:8]
        }
        return self._send_message("textcard", payload, to_user)

    def send_text(self, content: str, to_user: Optional[str] = None) -> bool:
        """发送纯文本消息."""
        return self._send_message("text", {"content": content}, to_user)

    def send_markdown(self, content: str, title: Optional[str] = None, to_user: Optional[str] = None) -> bool:
        """发送 Markdown (企业微信客户端原生渲染)."""
        return self._send_message("markdown", {"content": content}, to_user)

    def _send_message(self, msgtype: str, payload: Dict[str, Any], to_user: Optional[str] = None) -> bool:
        """底层消息发送逻辑."""
        token = self.get_access_token()
        target_user = to_user or self.default_to_user

        send_url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}"
        body = {
            "touser": target_user,
            "msgtype": msgtype,
            "agentid": self.agent_id,
            msgtype: payload,
            "safe": 0,
            "enable_id_trans": 0,
            "enable_duplicate_check": 0
        }

        try:
            resp = requests.post(send_url, json=body, timeout=10)
            result = resp.json()
        except Exception as e:
            logger.error(f"[WeChat] 发送消息网络异常: {e}")
            return False

        err_code = result.get("errcode")
        if err_code == 0:
            logger.info(f"[WeChat] 微信通知推送成功 ({msgtype}) -> {target_user}")
            return True

        if err_code == 60020:
            logger.error(f"[WeChat] 推送被拦截：当前出口 IP 未在企业微信白名单中！")
            return False

        if err_code in (40014, 42001, 41001):
            logger.warning(f"[WeChat] Token 失效 ({err_code})，尝试强制刷新后重发...")
            self.get_access_token(force_refresh=True)
            return self._send_message(msgtype, payload, to_user)

        logger.error(f"[WeChat] 发送消息失败 [code {err_code}]: {result.get('errmsg')}")
        return False
