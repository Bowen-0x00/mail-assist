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
        if self.config.api_key and self.config.api_key != "YOUR_LLM_API_KEY":
            http_client = httpx.Client(timeout=45.0)
            self.client = OpenAI(
                base_url=self.config.base_url,
                api_key=self.config.api_key,
                http_client=http_client
            )

    def is_configured(self) -> bool:
        """检查是否已正确配置 API Key."""
        return self.client is not None and bool(self.config.api_key) and self.config.api_key != "YOUR_LLM_API_KEY"

    def chat_json(self, system_prompt: str, user_prompt: str) -> Optional[Dict[str, Any]]:
        """调用大模型并返回解析后的 JSON 字典."""
        if not self.is_configured():
            logger.warning("[LLM] 尚未配置有效的 LLM api_key，跳过深度语义分析")
            return None

        try:
            response = self.client.chat.completions.create(
                model=self.config.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=self.config.temperature,
                response_format={"type": "json_object"}
            )
            raw_content = response.choices[0].message.content or "{}"
            return self._parse_json_safely(raw_content)
        except Exception as e:
            # 部分模型不支持 response_format={"type": "json_object"}，降级普通重试
            try:
                response = self.client.chat.completions.create(
                    model=self.config.model,
                    messages=[
                        {"role": "system", "content": system_prompt + "\n务必直接输出合法的标准 JSON，切勿包含其他多余解释或前后缀。"},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=self.config.temperature
                )
                raw_content = response.choices[0].message.content or "{}"
                return self._parse_json_safely(raw_content)
            except Exception as e2:
                logger.error(f"[LLM] 调用大语言模型失败: {e2}")
                return None

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
