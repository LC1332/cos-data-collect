"""多模型 VLM 客户端：统一接口调用 Gemini / OpenAI / ZhiPu / Anthropic 视觉模型。"""

import base64
import json
import logging
import mimetypes
import os
from pathlib import Path
from typing import Optional, Union

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

RECOGNITION_PROMPT = """\
你是一个ACG文化专家，特别擅长识别cosplay。请仔细观察图片中的人物，分析其在cos什么番剧/游戏中的什么角色。

以JSON形式返回你的分析和结果，并包含以下所有字段（按顺序逐步思考）：
- caption: 详细描述图片中人物的外观特点，包括发色、发型、服装、配饰、武器道具、姿态等信息
- analysis: 根据上述特征，分析该人物最可能是在cos什么番剧/游戏中的什么角色，给出推理过程
- character_name: 输出你认为最可能的cos角色名字（使用简体中文，如有通用译名请使用通用译名）
- bangumi_name: 输出该角色所属的番剧/游戏名字（使用简体中文，如有通用译名请使用通用译名）

请只返回JSON，不要添加其他内容。"""


MODEL_CONFIGS = {
    "gemini-3-flash": {
        "backend": "gemini",
        "model": "gemini-3-flash-preview",
        "base_url_env": "CUSTOM_BASE_URL_GEMINI",
        "api_key_env": "CUSTOM_API_KEY",
    },
    "gpt-5-mini": {
        "backend": "openai",
        "model": "gpt-5-mini",
        "base_url_env": "CUSTOM_BASE_URL_OPENAI",
        "api_key_env": "CUSTOM_API_KEY",
    },
    "GLM-4.6V-FlashX": {
        "backend": "openai",
        "model": "GLM-4.6V-FlashX",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "api_key_env": "GLM_API_KEY",
    },
    # claude-haiku: 当前转发网关未提供可用的 Anthropic OpenAI 兼容接口 (404)
    # 如需测试，在确认端点可用后取消注释并填写 base_url（勿将真实 URL 提交入库）
    # "claude-haiku": {
    #     "backend": "openai",
    #     "model": "claude-3-5-haiku-latest",
    #     "base_url": "<anthropic-openai-compatible-endpoint>",
    #     "api_key_env": "CUSTOM_API_KEY",
    # },
}


def _image_to_base64(image_path: Union[str, Path]) -> tuple[str, str]:
    """读取图片并返回 (base64_data, mime_type)。"""
    path = Path(image_path)
    mime, _ = mimetypes.guess_type(str(path))
    if not mime:
        mime = "image/jpeg"
    data = path.read_bytes()
    return base64.b64encode(data).decode("utf-8"), mime


def _parse_json_response(content: str) -> dict:
    """从可能包含 markdown 代码块的文本中提取 JSON。"""
    text = content.strip()
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        logger.warning("JSON 解析失败，返回原始文本")
        return {"raw_response": content.strip()}


def _call_gemini(
    image_path: Union[str, Path],
    prompt: str,
    config: dict,
) -> dict:
    """通过 google-genai 调用 Gemini VLM。"""
    from google import genai
    from google.genai import types

    api_key = os.getenv(config["api_key_env"], "").strip()
    base_url = (
        config.get("base_url")
        or os.getenv(config.get("base_url_env", ""), "").strip()
    )
    if not api_key or not base_url:
        raise ValueError(f"缺少 API 配置: {config['api_key_env']} / base_url")

    client = genai.Client(
        vertexai=True,
        api_key=api_key,
        http_options=types.HttpOptions(
            api_version="v1",
            headers={"Authorization": f"Bearer {api_key}"},
            base_url=base_url,
        ),
    )

    image_data = Path(image_path).read_bytes()
    _, mime = mimetypes.guess_type(str(image_path))
    if not mime:
        mime = "image/jpeg"

    response = client.models.generate_content(
        model=config["model"],
        contents=[
            types.Content(
                role="user",
                parts=[
                    types.Part.from_bytes(data=image_data, mime_type=mime),
                    types.Part.from_text(text=prompt),
                ],
            )
        ],
        config=types.GenerateContentConfig(
            temperature=0.3,
            max_output_tokens=4096,
        ),
    )
    return _parse_json_response(response.text or "")


def _call_openai_compatible(
    image_path: Union[str, Path],
    prompt: str,
    config: dict,
) -> dict:
    """通过 OpenAI 兼容接口（GPT / GLM / Claude 等）调用视觉模型。"""
    from openai import OpenAI

    api_key = os.getenv(config["api_key_env"], "").strip()
    base_url = (
        config.get("base_url")
        or os.getenv(config.get("base_url_env", ""), "").strip()
    )
    if not api_key or not base_url:
        raise ValueError(f"缺少 API 配置: {config['api_key_env']} / base_url")

    client = OpenAI(api_key=api_key, base_url=base_url)
    b64, mime = _image_to_base64(image_path)
    image_url = f"data:{mime};base64,{b64}"

    model_name = config["model"]
    kwargs: dict = dict(
        model=model_name,
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_url}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        stream=False,
    )

    _NEW_OPENAI = ("gpt-5", "gpt-4.1", "gpt-4o", "o1", "o3", "o4")
    if any(model_name.startswith(p) for p in _NEW_OPENAI):
        kwargs["max_completion_tokens"] = 4096
    else:
        kwargs["max_tokens"] = 4096
        kwargs["temperature"] = 0.3

    response = client.chat.completions.create(**kwargs)
    content = response.choices[0].message.content or ""
    return _parse_json_response(content)


def recognize_cosplay(
    image_path: Union[str, Path],
    model_name: str,
    prompt: Optional[str] = None,
) -> dict:
    """统一入口：对图片调用指定 VLM 模型进行 cosplay 角色识别。

    Returns:
        包含 caption / analysis / character_name / bangumi_name 的 dict，
        失败时包含 error 字段。
    """
    if model_name not in MODEL_CONFIGS:
        raise ValueError(f"未知模型: {model_name}, 可选: {list(MODEL_CONFIGS.keys())}")

    config = MODEL_CONFIGS[model_name]
    prompt = prompt or RECOGNITION_PROMPT

    logger.info(f"VLM 识别: model={model_name}, image={Path(image_path).name}")
    try:
        if config["backend"] == "gemini":
            return _call_gemini(image_path, prompt, config)
        else:
            return _call_openai_compatible(image_path, prompt, config)
    except Exception as e:
        logger.error(f"VLM 调用失败 ({model_name}): {e}")
        return {"error": str(e)}


def list_available_models() -> list[str]:
    """返回所有已配置且 API Key 可用的模型名。"""
    available = []
    for name, cfg in MODEL_CONFIGS.items():
        key = os.getenv(cfg["api_key_env"], "").strip()
        if key:
            available.append(name)
    return available
