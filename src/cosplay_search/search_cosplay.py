"""Cosplay 图片搜索流水线。

对每个角色依次：
1. 调用 gpt-5-mini 获取角色/番剧简称（有缓存则跳过）
2. 使用 "{简化角色名} cosplay {简化番剧名}" 搜索 Bing 图片
3. 下载 top 5 结果到 local_data/cosplay_images/{character_id}/

每个角色串行处理，天然控制请求频率。
"""

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

from better_bing_image_downloader import downloader as bing_downloader

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.brief_name.llm_client import get_llm_client, chat_completion_json
from src.brief_name.get_brief_names import (
    SYSTEM_PROMPT,
    USER_PROMPT_TEMPLATE,
    format_relations,
    load_characters,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

DATA_DIR = PROJECT_ROOT / "local_data" / "bangumi"
BRIEF_CACHE_DIR = PROJECT_ROOT / "local_data" / "brief_names"
COSPLAY_DIR = PROJECT_ROOT / "local_data" / "cosplay_images"
PROGRESS_FILE = PROJECT_ROOT / "local_data" / "cosplay_search_progress.json"

BRIEF_CACHE_DIR.mkdir(parents=True, exist_ok=True)
COSPLAY_DIR.mkdir(parents=True, exist_ok=True)

BRIEF_MODEL = "gpt-5-mini"
BRIEF_BASE_URL = None  # will read from env


def _brief_cache_path() -> Path:
    slug = BRIEF_MODEL.replace("/", "_").replace(" ", "_")
    return BRIEF_CACHE_DIR / f"brief_names_{slug}.json"


def load_brief_cache() -> Dict[str, dict]:
    path = _brief_cache_path()
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {str(item["char_id"]): item for item in data}
    return {}


def save_brief_cache(cache: Dict[str, dict]):
    path = _brief_cache_path()
    items = sorted(cache.values(), key=lambda x: x.get("char_id", 0))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def build_query(brief_name: str, brief_bangumi: str) -> str:
    return f"{brief_name} cosplay {brief_bangumi}"


def load_progress() -> dict:
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"completed": [], "failed": [], "char_query_map": {}}


def save_progress(progress: dict):
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)


def get_brief_name(client, character: dict, cache: Dict[str, dict]) -> Optional[dict]:
    """获取单个角色的简称，优先读缓存。"""
    char_id = str(character["id"])
    if char_id in cache:
        logger.info(f"  简称缓存命中: {character.get('name_cn') or character.get('name')}")
        return cache[char_id]

    name = character.get("name", "")
    name_cn = character.get("name_cn", "")
    relations = character.get("relations", [])

    user_prompt = USER_PROMPT_TEMPLATE.format(
        name=name,
        name_cn=name_cn,
        char_id=character["id"],
        relations_text=format_relations(relations),
    )

    try:
        result = chat_completion_json(
            client, SYSTEM_PROMPT, user_prompt, model=BRIEF_MODEL
        )
        result["char_id"] = character["id"]
        result["original_name"] = name
        result["original_name_cn"] = name_cn
        result["original_relations"] = relations
        cache[char_id] = result
        save_brief_cache(cache)
        logger.info(f"  LLM 简称获取成功: {result.get('brief_name')} / {result.get('brief_bangumi')}")
        return result
    except Exception as e:
        logger.error(f"  LLM 调用失败: {e}")
        return None


def _query_image_dir(query: str) -> Path:
    """库按搜索词创建子文件夹。"""
    return COSPLAY_DIR / query


def _count_images(folder: Path) -> int:
    if not folder.exists():
        return 0
    return sum(1 for f in folder.iterdir() if f.is_file() and not f.name.startswith("_"))


def search_cosplay_images(
    char_id: int,
    brief_name: str,
    brief_bangumi: str,
    limit: int = 5,
) -> int:
    """用 Bing 搜索 cosplay 图片并下载到本地。返回实际下载数量。"""
    query = build_query(brief_name, brief_bangumi)
    query_dir = _query_image_dir(query)

    existing = _count_images(query_dir)
    if existing >= limit:
        logger.info(f"  已有 {existing} 张图片，跳过下载")
        return existing

    logger.info(f"  搜索关键词: \"{query}\"")
    try:
        count = bing_downloader(
            query=query,
            limit=limit,
            output_dir=str(COSPLAY_DIR),
            name=str(char_id),
            adult_filter_off=False,
            force_replace=False,
            timeout=30,
            verbose=False,
        )
        downloaded = count if isinstance(count, int) else 0
        logger.info(f"  下载完成: {downloaded} 张图片")
        return downloaded
    except Exception as e:
        logger.error(f"  图片下载失败: {e}")
        return 0


def run_pipeline(
    top_n: int = 30,
    limit_per_char: int = 5,
    delay_between: float = 2.0,
):
    """主流水线：逐个角色获取简称 + 下载 cosplay 图片。"""
    base_url = os.getenv("WINKY_BASE_URL_OPENAI", "").strip()
    if not base_url:
        raise ValueError("请在 .env 中配置 WINKY_BASE_URL_OPENAI")
    client = get_llm_client(base_url=base_url)
    brief_cache = load_brief_cache()
    progress = load_progress()
    characters = load_characters(top_n=top_n)

    logger.info(f"=== Cosplay 搜索流水线启动 ===")
    logger.info(f"角色数量: {len(characters)}, 每角色下载: {limit_per_char} 张")

    for i, ch in enumerate(characters):
        char_id = ch["id"]
        char_label = ch.get("name_cn") or ch.get("name", str(char_id))

        if char_id in progress["completed"]:
            logger.info(f"[{i+1}/{len(characters)}] 跳过已完成: {char_label}")
            continue

        logger.info(f"[{i+1}/{len(characters)}] 处理: {char_label} (id={char_id})")

        # Step 1: 获取简称
        brief = get_brief_name(client, ch, brief_cache)
        if not brief or "brief_name" not in brief:
            logger.warning(f"  无法获取简称，跳过")
            progress["failed"].append(char_id)
            save_progress(progress)
            continue

        brief_name = brief["brief_name"]
        brief_bangumi = brief.get("brief_bangumi", "")

        # Step 2: 搜索下载 cosplay 图片
        downloaded = search_cosplay_images(
            char_id, brief_name, brief_bangumi, limit=limit_per_char
        )

        # 记录进度和 char_id -> query 映射
        query = build_query(brief_name, brief_bangumi)
        if "char_query_map" not in progress:
            progress["char_query_map"] = {}
        progress["char_query_map"][str(char_id)] = query

        if downloaded > 0:
            progress["completed"].append(char_id)
        else:
            progress["failed"].append(char_id)
        save_progress(progress)

        # 间隔延迟，避免冲击服务器
        if i < len(characters) - 1:
            logger.info(f"  等待 {delay_between}s ...")
            time.sleep(delay_between)

    logger.info(f"=== 流水线完成 ===")
    logger.info(f"成功: {len(progress['completed'])}, 失败: {len(progress['failed'])}")


def generate_cosplay_html(top_n: int = 30):
    """生成 HTML 页面展示 cosplay 搜索结果与原角色图的对比。"""
    characters = load_characters(top_n=top_n)
    brief_cache = load_brief_cache()
    progress = load_progress()
    char_query_map = progress.get("char_query_map", {})

    html_parts = [
        "<!DOCTYPE html>",
        "<html lang='zh-CN'>",
        "<head>",
        "<meta charset='UTF-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1.0'>",
        "<title>Cosplay 搜索结果 - Top {}</title>".format(top_n),
        "<style>",
        """
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: #0f0f0f; color: #e0e0e0; padding: 20px;
        }
        h1 {
            text-align: center; padding: 30px 0; font-size: 28px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        }
        .stats {
            text-align: center; color: #888; margin-bottom: 30px; font-size: 14px;
        }
        .character-card {
            background: #1a1a2e; border-radius: 12px; margin-bottom: 24px;
            padding: 20px; border: 1px solid #2a2a3e;
        }
        .character-header {
            display: flex; align-items: center; gap: 16px; margin-bottom: 16px;
        }
        .character-header h2 {
            font-size: 20px; color: #fff;
        }
        .character-header .meta {
            font-size: 13px; color: #888;
        }
        .search-query {
            font-size: 13px; color: #667eea; margin-bottom: 12px;
            font-style: italic;
        }
        .image-row {
            display: flex; gap: 12px; overflow-x: auto; padding-bottom: 8px;
        }
        .image-cell {
            flex-shrink: 0; text-align: center;
        }
        .image-cell img {
            width: 180px; height: 240px; object-fit: contain;
            border-radius: 8px; border: 2px solid #333;
            background: #111; transition: transform 0.2s;
        }
        .image-cell img:hover { transform: scale(1.05); border-color: #667eea; }
        .image-cell .label {
            font-size: 12px; color: #888; margin-top: 4px;
        }
        .original img { border-color: #764ba2; }
        .no-image {
            width: 180px; height: 240px; border-radius: 8px;
            background: #2a2a3e; display: flex; align-items: center;
            justify-content: center; color: #555; font-size: 13px;
            border: 2px dashed #333;
        }
        .rank-badge {
            background: linear-gradient(135deg, #667eea, #764ba2);
            color: #fff; padding: 2px 10px; border-radius: 12px;
            font-size: 13px; font-weight: bold;
        }
        """,
        "</style>",
        "</head>",
        "<body>",
        "<h1>Cosplay 搜索结果对比</h1>",
        '<p class="stats">Top {} 角色 | 每角色搜索 5 张 Cosplay 图片</p>'.format(top_n),
    ]

    for i, ch in enumerate(characters):
        char_id = ch["id"]
        char_label = ch.get("name_cn") or ch.get("name", "")
        char_name_jp = ch.get("name", "")

        brief = brief_cache.get(str(char_id), {})
        brief_name = brief.get("brief_name", char_label)
        brief_bangumi = brief.get("brief_bangumi", "")
        query = f"{brief_name} cosplay {brief_bangumi}"

        # 角色原图 (优先 local, fallback remote)
        original_local = None
        for suffix in ["large", "medium"]:
            p = DATA_DIR / "character_images" / f"{char_id}_{suffix}.jpg"
            if p.exists():
                original_local = os.path.relpath(p, COSPLAY_DIR.parent)
                break
        if not original_local:
            images = ch.get("images", {})
            original_local = images.get("large") or images.get("medium") or ""

        # cosplay 图片（库按搜索词创建文件夹）
        cosplay_images = []
        folder_query = char_query_map.get(str(char_id), query)
        char_cos_dir = COSPLAY_DIR / folder_query
        if char_cos_dir.exists():
            for f in sorted(char_cos_dir.iterdir()):
                if f.is_file() and not f.name.startswith("_"):
                    cosplay_images.append(os.path.relpath(f, COSPLAY_DIR.parent))

        relations_str = ", ".join(
            r["subject_name"] for r in ch.get("relations", [])[:3]
        )

        html_parts.append('<div class="character-card">')
        html_parts.append('<div class="character-header">')
        html_parts.append(f'<span class="rank-badge">#{i+1}</span>')
        html_parts.append(f'<div><h2>{char_label}</h2>')
        html_parts.append(f'<div class="meta">{char_name_jp} | ID: {char_id} | {relations_str}</div></div>')
        html_parts.append("</div>")
        html_parts.append(f'<div class="search-query">搜索词: {query}</div>')
        html_parts.append('<div class="image-row">')

        # 原角色图
        html_parts.append('<div class="image-cell original">')
        if original_local:
            html_parts.append(f'<img src="{original_local}" alt="原角色图" loading="lazy">')
        else:
            html_parts.append('<div class="no-image">无原图</div>')
        html_parts.append('<div class="label">原角色图</div>')
        html_parts.append("</div>")

        # cosplay 结果图
        for j in range(5):
            html_parts.append('<div class="image-cell">')
            if j < len(cosplay_images):
                html_parts.append(f'<img src="{cosplay_images[j]}" alt="cosplay #{j+1}" loading="lazy">')
            else:
                html_parts.append('<div class="no-image">无结果</div>')
            html_parts.append(f'<div class="label">搜索结果 #{j+1}</div>')
            html_parts.append("</div>")

        html_parts.append("</div>")  # image-row
        html_parts.append("</div>")  # character-card

    html_parts.append("</body></html>")

    out_path = PROJECT_ROOT / "local_data" / "cosplay_gallery.html"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(html_parts))
    logger.info(f"HTML 页面已生成: {out_path}")
    return out_path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Cosplay 图片搜索流水线")
    parser.add_argument("--top-n", type=int, default=30, help="处理前 N 个角色")
    parser.add_argument("--limit", type=int, default=5, help="每角色下载图片数")
    parser.add_argument("--delay", type=float, default=2.0, help="角色间延迟(秒)")
    parser.add_argument("--html-only", action="store_true", help="仅生成 HTML 不下载")
    args = parser.parse_args()

    if args.html_only:
        generate_cosplay_html(top_n=args.top_n)
    else:
        run_pipeline(
            top_n=args.top_n,
            limit_per_char=args.limit,
            delay_between=args.delay,
        )
        generate_cosplay_html(top_n=args.top_n)
