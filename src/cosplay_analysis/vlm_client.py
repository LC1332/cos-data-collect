"""Gemini VLM 客户端：通过环境变量指定的 Base URL 调用 Gemini，用于 cosplay 图片多模态分析。"""

import json
import logging
import os
from pathlib import Path
from typing import Optional, Union

from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

VLM_MODEL = "gemini-3-flash-preview"

ANALYSIS_PROMPT_TEMPLATE = """\
请帮助我判断每个pics是否是对 Original_Character 的cosplay

我正在寻找 {bangumi_name} 中 {character_name} 的cosplay

在左上角我给出了这个角色的原图，并且之后给出了一些搜索结果

以JSON形式返回你的分析和结果，并包含以下所有字段
- analysis_if_cosplay_image 分析每张图是否是真实风格的cosplay图片，
- analysis_if_correct_character 分析每张图是否相对正确的表达了需要cos的角色，还是错误命中了番剧中的其他无关角色等等。注意一个角色可能在剧中有多套衣服的设定，不一定完全和original-character的服装相同
{pic_fields}

请只返回JSON，不要添加其他内容。"""


def _build_pic_fields(num_pics: int) -> str:
    labels = ["A", "B", "C", "D", "E"][:num_pics]
    lines = []
    for lb in labels:
        lines.append(
            f'- if_{lb}_correct 如果{lb}图片是正确的cos图片，返回"true"，不然是"false"'
        )
    return "\n".join(lines)


def get_gemini_client() -> genai.Client:
    api_key = os.getenv("CUSTOM_API_KEY", "").strip()
    base_url = os.getenv("CUSTOM_BASE_URL_GEMINI", "").strip()
    if not api_key:
        raise ValueError("请在 .env 中配置 CUSTOM_API_KEY")
    if not base_url:
        raise ValueError("请在 .env 中配置 CUSTOM_BASE_URL_GEMINI")
    return genai.Client(
        vertexai=True,
        api_key=api_key,
        http_options=types.HttpOptions(
            api_version="v1",
            headers={"Authorization": f"Bearer {api_key}"},
            base_url=base_url,
        ),
    )


def analyze_cosplay(
    client: genai.Client,
    grid_image_path: Union[str, Path],
    character_name: str,
    bangumi_name: str,
    num_pics: int = 5,
    model: str = VLM_MODEL,
) -> dict:
    """发送网格图到 Gemini VLM，判断每张图是否为正确的 cosplay。"""
    grid_path = Path(grid_image_path)
    image_data = grid_path.read_bytes()

    prompt = ANALYSIS_PROMPT_TEMPLATE.format(
        bangumi_name=bangumi_name,
        character_name=character_name,
        pic_fields=_build_pic_fields(num_pics),
    )

    image_part = types.Part.from_bytes(data=image_data, mime_type="image/jpeg")
    text_part = types.Part.from_text(text=prompt)

    logger.info(f"VLM 分析: {character_name} ({bangumi_name}), model={model}")

    response = client.models.generate_content(
        model=model,
        contents=[
            types.Content(role="user", parts=[image_part, text_part])
        ],
        config=types.GenerateContentConfig(
            temperature=0.3,
            max_output_tokens=4096,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )

    content = (response.text or "").strip()
    logger.debug(f"VLM 原始返回:\n{content}")

    if "```json" in content:
        content = content.split("```json", 1)[1].split("```", 1)[0].strip()
    elif "```" in content:
        content = content.split("```", 1)[1].split("```", 1)[0].strip()

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        logger.warning(f"VLM JSON 解析失败，返回原始文本包装")
        return {"raw_response": content}


def count_correct(vlm_result: dict, num_pics: int = 5) -> int:
    """统计 VLM 结果中判定为正确的 cosplay 图片数量。"""
    labels = ["A", "B", "C", "D", "E"][:num_pics]
    count = 0
    for lb in labels:
        key = f"if_{lb}_correct"
        val = str(vlm_result.get(key, "false")).lower().strip('"')
        if val == "true":
            count += 1
    return count


def get_correct_indices(vlm_result: dict, num_pics: int = 5) -> list:
    """返回被判定为正确 cosplay 的图片索引列表（0-based）。"""
    labels = ["A", "B", "C", "D", "E"][:num_pics]
    indices = []
    for i, lb in enumerate(labels):
        key = f"if_{lb}_correct"
        val = str(vlm_result.get(key, "false")).lower().strip('"')
        if val == "true":
            indices.append(i)
    return indices
