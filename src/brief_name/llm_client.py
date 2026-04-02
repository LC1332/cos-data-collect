"""LLM 客户端：通过 OpenAI 兼容接口调用 Winky 代理的模型。"""

import os
import json
import logging
from typing import Optional

from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


def get_llm_client(base_url: Optional[str] = None) -> OpenAI:
    api_key = os.getenv("WINKY_API_KEY", "").strip()
    base_url = base_url or os.getenv("WINKY_BASE_URL", "").strip()
    if not api_key or not base_url:
        raise ValueError("请在 .env 中配置 WINKY_API_KEY 和 WINKY_BASE_URL")
    return OpenAI(api_key=api_key, base_url=base_url)


_OPENAI_NEW_MODELS = ("gpt-5", "gpt-4.1", "gpt-4o", "o1", "o3", "o4")


def _is_new_openai_model(model: str) -> bool:
    return any(model.startswith(prefix) for prefix in _OPENAI_NEW_MODELS)


def chat_completion_json(
    client: OpenAI,
    system_prompt: str,
    user_prompt: str,
    model: Optional[str] = None,
    temperature: float = 0.3,
    max_tokens: int = 2048,
) -> dict:
    """发送聊天请求并尝试解析 JSON 返回。"""
    model = model or os.getenv("WINKY_MODEL", "deepseek-chat")
    logger.info(f"调用 LLM: model={model}, prompt长度={len(user_prompt)}")

    kwargs = dict(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        stream=False,
    )
    if _is_new_openai_model(model):
        kwargs["max_completion_tokens"] = max_tokens
    else:
        kwargs["max_tokens"] = max_tokens
        kwargs["temperature"] = temperature

    response = client.chat.completions.create(**kwargs)

    content = response.choices[0].message.content.strip()
    logger.debug(f"LLM 原始返回:\n{content}")

    # 尝试从 markdown 代码块中提取 JSON
    if "```json" in content:
        content = content.split("```json", 1)[1]
        content = content.split("```", 1)[0].strip()
    elif "```" in content:
        content = content.split("```", 1)[1]
        content = content.split("```", 1)[0].strip()

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        logger.warning(f"JSON 解析失败，返回原始文本包装")
        return {"raw_response": content}
