"""Bangumi 数据采集主入口。

功能:
1. 获取人气 top 300 番剧
2. 尝试获取人气 top 500 / 3000 角色 (通过角色收藏数排序)
3. 从 top 300 番剧中提取主要角色作为补充
4. 取并集，输出最终角色列表
"""

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.bangumi.api_client import BangumiClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

DATA_DIR = PROJECT_ROOT / "local_data" / "bangumi"
INFO_DIR = PROJECT_ROOT / "information"
DATA_DIR.mkdir(parents=True, exist_ok=True)
INFO_DIR.mkdir(parents=True, exist_ok=True)


def fetch_top_anime(client: BangumiClient, top_n: int = 300) -> List[dict]:
    """通过 GET /v0/subjects 获取排名前 N 的动画。

    API limit 上限为 50，需要分页。
    """
    PAGE_SIZE = 50
    results = []  # type: List[dict]
    offset = 0

    while offset < top_n:
        limit = min(PAGE_SIZE, top_n - offset)
        logger.info(f"正在获取番剧排行: offset={offset}, limit={limit}")
        page = client.browse_subjects(
            subject_type=2, sort="rank", limit=limit, offset=offset,
        )
        data = page.get("data", [])
        if not data:
            logger.warning(f"offset={offset} 时返回空数据，提前结束")
            break
        results.extend(data)
        offset += len(data)

    logger.info(f"共获取 {len(results)} 部番剧")
    return results


def fetch_characters_from_anime(
    client: BangumiClient,
    anime_list: List[dict],
    main_only: bool = True,
) -> Dict[int, dict]:
    """从番剧列表中提取角色。返回 {character_id: info}。

    main_only=True 时只取"主角"关系的角色。
    """
    characters = {}  # type: Dict[int, dict]
    total = len(anime_list)

    for idx, anime in enumerate(anime_list):
        subject_id = anime["id"]
        subject_name = anime.get("name_cn") or anime.get("name", "")
        logger.info(f"[{idx+1}/{total}] 获取角色: {subject_name} (id={subject_id})")

        try:
            char_list = client.get_subject_characters(subject_id)
        except Exception as e:
            logger.warning(f"  获取角色失败: {e}")
            continue

        for ch in char_list:
            cid = ch["id"]
            relation = ch.get("relation", "")
            if main_only and relation != "主角":
                continue
            if cid not in characters:
                characters[cid] = {
                    "id": cid,
                    "name": ch.get("name", ""),
                    "type": ch.get("type", 1),
                    "relation": relation,
                    "images": ch.get("images"),
                    "from_subjects": [],
                }
            characters[cid]["from_subjects"].append({
                "subject_id": subject_id,
                "subject_name": subject_name,
                "relation": relation,
            })

    logger.info(f"从番剧中提取到 {len(characters)} 个角色")
    return characters


def enrich_character_details(
    client: BangumiClient,
    characters: Dict[int, dict],
) -> Dict[int, dict]:
    """为每个角色补充详细信息 (stat.collects 用于排序)。"""
    total = len(characters)
    for idx, (cid, info) in enumerate(characters.items()):
        logger.info(f"[{idx+1}/{total}] 补充角色详情: {info['name']} (id={cid})")
        try:
            detail = client.get_character(cid)
            stat = detail.get("stat", {})
            info["collects"] = stat.get("collects", 0)
            info["comments"] = stat.get("comments", 0)
            info["summary"] = detail.get("summary", "")
            info["name_cn"] = ""
            for item in (detail.get("infobox") or []):
                if item.get("key") == "简体中文名":
                    info["name_cn"] = item.get("value", "")
                    break
            info["gender"] = detail.get("gender", "")
            info["images"] = detail.get("images") or info.get("images")
        except Exception as e:
            logger.warning(f"  获取详情失败: {e}")
            info.setdefault("collects", 0)

    return characters


def try_fetch_top_characters_via_search(
    client: BangumiClient,
    target: int = 500,
) -> List[dict]:
    """尝试通过搜索接口获取人气角色。

    search/characters 需要 keyword 且无 sort 选项，
    所以用单字母/常见词作为宽泛关键词来尽量覆盖更多角色，
    再按 collects 排序去重。这是一种尽力而为的方案。
    """
    logger.info(f"尝试通过搜索接口获取 top {target} 角色...")
    seen_ids = set()   # type: set
    all_chars = []     # type: List[dict]

    broad_keywords = ["の", "ア", "ル", "リ", "ン", "マ", "ス", "カ", "レ", "ト"]

    for kw in broad_keywords:
        logger.info(f"  搜索关键词: '{kw}'")
        offset = 0
        while offset < 200:
            try:
                result = client.search_characters(kw, limit=50, offset=offset)
            except Exception as e:
                logger.warning(f"    搜索失败: {e}")
                break
            data = result.get("data", [])
            if not data:
                break
            for ch in data:
                cid = ch["id"]
                if cid not in seen_ids:
                    seen_ids.add(cid)
                    all_chars.append(ch)
            offset += len(data)

        if len(all_chars) >= target * 3:
            break

    logger.info(f"  搜索共获取 {len(all_chars)} 个去重角色，开始获取详情用于排序...")

    enriched = []  # type: List[dict]
    for idx, ch in enumerate(all_chars):
        cid = ch["id"]
        if idx % 50 == 0:
            logger.info(f"  补充详情进度: {idx}/{len(all_chars)}")
        try:
            detail = client.get_character(cid)
            stat = detail.get("stat", {})
            enriched.append({
                "id": cid,
                "name": ch.get("name", ""),
                "collects": stat.get("collects", 0),
                "comments": stat.get("comments", 0),
                "summary": detail.get("summary", ""),
                "images": detail.get("images"),
                "gender": detail.get("gender", ""),
            })
        except Exception:
            pass

    enriched.sort(key=lambda x: x["collects"], reverse=True)
    logger.info(
        f"搜索方案获取到 {len(enriched)} 个角色"
        + (f"，top1 collects={enriched[0]['collects']}" if enriched else "")
    )
    return enriched[:target]


def save_json(data, filename: str, directory: Path = DATA_DIR):
    path = directory / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"已保存: {path}")


def generate_summary(
    anime_list: List[dict],
    characters_from_anime: Dict[int, dict],
    search_characters: List[dict],
    merged_characters: List[dict],
):
    """生成汇总信息到 information/ 目录。"""
    lines = [
        "# Bangumi 数据采集汇总\n",
        f"## 番剧 Top List",
        f"- 共获取 **{len(anime_list)}** 部番剧（按排名排序）\n",
        "| 排名 | ID | 名称 | 中文名 | 评分 | 排名值 |",
        "|------|-----|------|--------|------|--------|",
    ]
    for i, a in enumerate(anime_list[:50], 1):
        name = a.get("name", "")
        name_cn = a.get("name_cn", "")
        rating = a.get("rating", {})
        score = rating.get("score", "N/A")
        rank = rating.get("rank", "N/A")
        lines.append(f"| {i} | {a['id']} | {name} | {name_cn} | {score} | {rank} |")
    if len(anime_list) > 50:
        lines.append(f"\n*（仅展示前 50 部，完整列表见 local_data/bangumi/top_anime.json）*\n")

    lines.append(f"\n## 角色列表")
    lines.append(f"- 从番剧中提取的主角: **{len(characters_from_anime)}** 个")
    lines.append(f"- 搜索接口获取角色: **{len(search_characters)}** 个")
    lines.append(f"- 合并去重后: **{len(merged_characters)}** 个\n")

    lines.append("### Top 50 角色（按收藏数排序）")
    lines.append("| 排名 | ID | 名称 | 中文名 | 收藏数 | 来源番剧 |")
    lines.append("|------|-----|------|--------|--------|----------|")
    for i, ch in enumerate(merged_characters[:50], 1):
        name = ch.get("name", "")
        name_cn = ch.get("name_cn", "")
        collects = ch.get("collects", 0)
        subjects = ch.get("from_subjects", [])
        subj_str = ", ".join(s["subject_name"] for s in subjects[:3]) if subjects else "-"
        lines.append(f"| {i} | {ch['id']} | {name} | {name_cn} | {collects} | {subj_str} |")
    if len(merged_characters) > 50:
        lines.append(f"\n*（仅展示前 50 个，完整列表见 local_data/bangumi/merged_characters.json）*\n")

    summary_path = INFO_DIR / "bangumi_summary.md"
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    logger.info(f"汇总已保存: {summary_path}")


def main():
    client = BangumiClient()
    logger.info("=" * 60)
    logger.info("Bangumi 数据采集开始")
    logger.info("=" * 60)

    # ── Step 1: 获取 top 300 番剧 ──
    logger.info("\n[Step 1] 获取人气 Top 300 番剧")
    anime_list = fetch_top_anime(client, top_n=300)
    save_json(anime_list, "top_anime.json")

    # ── Step 2: 尝试通过搜索获取 top 角色 ──
    logger.info("\n[Step 2] 尝试通过搜索获取人气 Top 500 角色")
    search_chars = try_fetch_top_characters_via_search(client, target=500)
    save_json(search_chars, "search_top_characters.json")

    # ── Step 3: 从 top 300 番剧提取主角 ──
    logger.info("\n[Step 3] 从 Top 300 番剧中提取主要角色")
    anime_characters = fetch_characters_from_anime(client, anime_list, main_only=True)

    logger.info("\n[Step 3.5] 补充角色详细信息")
    anime_characters = enrich_character_details(client, anime_characters)
    anime_chars_list = sorted(
        anime_characters.values(), key=lambda x: x.get("collects", 0), reverse=True,
    )
    save_json(anime_chars_list, "anime_main_characters.json")

    # ── Step 4: 合并去重 ──
    logger.info("\n[Step 4] 合并两个来源的角色列表")
    merged = {}  # type: Dict[int, dict]
    for ch in anime_chars_list:
        merged[ch["id"]] = ch
    for ch in search_chars:
        cid = ch["id"]
        if cid not in merged:
            merged[cid] = ch
        else:
            if ch.get("collects", 0) > merged[cid].get("collects", 0):
                from_subjects = merged[cid].get("from_subjects", [])
                merged[cid].update(ch)
                merged[cid]["from_subjects"] = from_subjects

    merged_list = sorted(merged.values(), key=lambda x: x.get("collects", 0), reverse=True)
    save_json(merged_list, "merged_characters.json")
    logger.info(f"合并后共 {len(merged_list)} 个角色")

    # ── Step 5: 生成汇总 ──
    logger.info("\n[Step 5] 生成汇总报告")
    generate_summary(anime_list, anime_characters, search_chars, merged_list)

    logger.info("\n" + "=" * 60)
    logger.info("采集完成!")
    logger.info(f"  番剧数量: {len(anime_list)}")
    logger.info(f"  角色数量(合并后): {len(merged_list)}")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
