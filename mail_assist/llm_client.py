"""LLM 客户端包装模块 (兼容 OpenAI 规范)."""

import json
import re
import httpx
from typing import Dict, Any, Optional
from openai import OpenAI
from loguru import logger
from .config import LLMConfig

class LLMClient:
    """兼容 OpenAI 接口标准的统一大模型调用器."""

    def __init__(self, config: LLMConfig):
        self.config = config
        self.client: Optional[OpenAI] = None
        self.direct_client: Optional[OpenAI] = None
        self.last_error: Optional[str] = None

        if self.config.api_key and self.config.api_key != "YOUR_LLM_API_KEY":
            proxy = getattr(self.config, "proxy", None)
            http_client = httpx.Client(timeout=35.0, proxy=proxy) if proxy else httpx.Client(timeout=35.0)
            self.client = OpenAI(
                base_url=self.config.base_url,
                api_key=self.config.api_key,
                http_client=http_client
            )
            if proxy:
                self.direct_client = OpenAI(
                    base_url=self.config.base_url,
                    api_key=self.config.api_key,
                    http_client=httpx.Client(timeout=35.0)
                )
            else:
                self.direct_client = self.client

    def _call_chat_completions(self, messages, response_format=None) -> str:
        """调用大模型，具备自动多候选模型故障转移与代理连接故障自愈能力."""
        candidate_models = [self.config.model, "gemini-3.1-pro-preview", "gemini-3.6-flash", "gemini-3.8-flash", "deepseek-chat"]
        seen = set()
        ordered = []
        for m in candidate_models:
            if m and m not in seen:
                seen.add(m)
                ordered.append(m)

        clients = [self.client]
        if self.direct_client and self.direct_client is not self.client:
            clients.append(self.direct_client)

        last_err = None
        for cli in clients:
            for m in ordered:
                try:
                    kwargs = {
                        "model": m,
                        "messages": messages,
                        "temperature": self.config.temperature
                    }
                    if response_format:
                        kwargs["response_format"] = response_format
                    resp = cli.chat.completions.create(**kwargs)
                    content = resp.choices[0].message.content or ""
                    if content.strip():
                        if m != self.config.model:
                            logger.info(f"[LLM] 模型 [{self.config.model}] 异常，成功故障转移至 [{m}]")
                        return content
                except Exception as e:
                    last_err = e
                    continue
        raise last_err or RuntimeError("所有大模型通道均不可用")

    def test_model(self, model_name: str) -> tuple[bool, str]:
        """测试指定模型连通性与时延."""
        if not self.is_configured():
            return False, "未配置 API Key"
        import time
        start_time = time.time()
        clients = [self.client]
        if self.direct_client and self.direct_client is not self.client:
            clients.append(self.direct_client)
        last_err = ""
        for cli in clients:
            try:
                resp = cli.chat.completions.create(
                    model=model_name,
                    messages=[{"role": "user", "content": "hi"}],
                    max_tokens=5,
                    timeout=8.0
                )
                cost = time.time() - start_time
                if resp.choices and resp.choices[0].message:
                    return True, f"{cost:.2f}s"
            except Exception as e:
                last_err = str(e)
                continue
        return False, last_err[:120]

    def is_configured(self) -> bool:
        """检查是否已正确配置 API Key."""
        return self.client is not None and bool(self.config.api_key) and self.config.api_key != "YOUR_LLM_API_KEY"

    def chat_json(self, system_prompt: str, user_prompt: str) -> Optional[Dict[str, Any]]:
        """调用大模型并返回解析后的 JSON 字典."""
        if not self.is_configured():
            logger.warning("[LLM] 尚未配置有效的 LLM api_key，跳过深度语义分析")
            return None

        try:
            raw_content = self._call_chat_completions(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                response_format={"type": "json_object"}
            )
            self.last_error = None
            return self._parse_json_safely(raw_content)
        except Exception as e:
            self.last_error = str(e)
            logger.error(f"[LLM] 调用大语言模型失败: {e}")
            return None

    def chat_text(self, messages: list) -> str:
        """常规对话补全 (用于 /llm 追问)."""
        if not self.is_configured():
            return "⚠️ 未配置有效 API Key。"
        try:
            ans = self._call_chat_completions(messages)
            self.last_error = None
            return ans.strip() or "未能获取有效回答。"
        except Exception as e:
            self.last_error = str(e)
            logger.error(f"[LLM] 追问对话异常: {e}")
            return f"⚠️ 追问回答生成失败: {e}"
    def _parse_json_safely(self, text: str) -> Dict[str, Any]:
        """清理并解析大模型返回的 JSON 字符串."""
        text = text.strip()
        # 剥离 ```json ... ``` 标记
        match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', text)
        if match:
            text = match.group(1).strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # 尝试提取首个花括号对
            brace_match = re.search(r'\{[\s\S]*\}', text)
            if brace_match:
                try:
                    return json.loads(brace_match.group(0))
                except Exception:
                    pass
            logger.warning(f"[LLM] 无法将模型响应解析为合法 JSON: {text[:150]}...")
            return {}
