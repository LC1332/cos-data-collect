"""Bangumi 数据采集主入口。

策略: 从 top 番剧出发 → 获取每部番剧的角色 → 建立番剧-角色关联 → 按收藏数排序。
这样既保证角色来自热门番剧，又自然地维护了番剧和角色的关系。
"""

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

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


# ── 工具函数 ──

def save_json(data, filename, directory=DATA_DIR):
    path = directory / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"已保存: {path}  ({_sizeof(data)} 条)")


def load_json(filename, directory=DATA_DIR):
    path = directory / filename
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return None


def _sizeof(data):
    if isinstance(data, list):
        return len(data)
    if isinstance(data, dict):
        return len(data)
    return "?"


# ── Step 1: 获取 top N 番剧 ──

def fetch_top_anime(client, top_n=300, cache_file="top_anime.json"):
    """通过 GET /v0/subjects?type=2&sort=rank 分页获取排名前 N 的动画。"""
    cached = load_json(cache_file)
    if cached and len(cached) >= top_n:
        logger.info(f"使用缓存的番剧列表 ({len(cached)} 部)")
        return cached[:top_n]

    PAGE_SIZE = 50
    results = []
    offset = 0
    while offset < top_n:
        limit = min(PAGE_SIZE, top_n - offset)
        logger.info(f"  获取番剧排行: offset={offset}, limit={limit}")
        page = client.browse_subjects(subject_type=2, sort="rank", limit=limit, offset=offset)
        data = page.get("data", [])
        if not data:
            break
        results.extend(data)
        offset += len(data)

    logger.info(f"共获取 {len(results)} 部番剧")
    save_json(results, cache_file)
    return results


# ── Step 2: 从番剧获取角色 & 建立关联 ──

def fetch_characters_from_anime(
    client, anime_list, cache_file="anime_characters_raw.json",
):
    """为每部番剧调用 /v0/subjects/{id}/characters，返回:

    characters: {char_id: {id, name, type, relations: [{subject_id, subject_name, relation}]}}
    """
    cached = load_json(cache_file)
    if cached:
        logger.info(f"使用缓存的番剧角色关联 ({len(cached)} 个角色)")
        return cached

    characters = {}  # type: Dict[int, dict]
    total = len(anime_list)

    for idx, anime in enumerate(anime_list):
        sid = anime["id"]
        sname = anime.get("name_cn") or anime.get("name", "")
        logger.info(f"  [{idx+1}/{total}] {sname} (id={sid})")

        try:
            char_list = client.get_subject_characters(sid)
        except Exception as e:
            logger.warning(f"    失败: {e}")
            continue

        for ch in char_list:
            cid = ch["id"]
            relation = ch.get("relation", "")
            if cid not in characters:
                characters[cid] = {
                    "id": cid,
                    "name": ch.get("name", ""),
                    "type": ch.get("type", 1),
                    "images": ch.get("images"),
                    "relations": [],
                }
            characters[cid]["relations"].append({
                "subject_id": sid,
                "subject_name": sname,
                "relation": relation,
            })

    char_list_out = list(characters.values())
    save_json(char_list_out, cache_file)
    logger.info(f"共提取 {len(char_list_out)} 个去重角色")
    return char_list_out


# ── Step 3: 补充角色详情 (collects) ──

def enrich_characters(client, char_list, cache_file="characters_enriched.json"):
    """为每个角色请求详情，补充 collects / name_cn / gender 等字段。
    
    支持断点续传：已有 collects 字段的跳过。
    """
    cached = load_json(cache_file)
    if cached:
        enriched_ids = {ch["id"] for ch in cached if "collects" in ch}
        if enriched_ids:
            id_to_cached = {ch["id"]: ch for ch in cached}
            for ch in char_list:
                if ch["id"] in id_to_cached:
                    ch.update(id_to_cached[ch["id"]])
            need_enrich = [ch for ch in char_list if "collects" not in ch]
            if not need_enrich:
                logger.info(f"使用缓存的角色详情 ({len(cached)} 个角色均已补充)")
                return char_list
            logger.info(f"断点续传: 已有 {len(enriched_ids)} 个，还需补充 {len(need_enrich)} 个")

    total = len(char_list)
    need_enrich = [ch for ch in char_list if "collects" not in ch]
    logger.info(f"需要补充详情的角色: {len(need_enrich)} / {total}")

    for idx, ch in enumerate(need_enrich):
        cid = ch["id"]
        if idx % 100 == 0:
            logger.info(f"  补充详情进度: {idx}/{len(need_enrich)}")
            if idx > 0:
                save_json(char_list, cache_file)
        try:
            detail = client.get_character(cid)
            stat = detail.get("stat", {})
            ch["collects"] = stat.get("collects", 0)
            ch["comments"] = stat.get("comments", 0)
            ch["summary"] = detail.get("summary", "")
            ch["gender"] = detail.get("gender", "")
            ch["images"] = detail.get("images") or ch.get("images")
            # 从 infobox 提取中文名
            for item in (detail.get("infobox") or []):
                if item.get("key") == "简体中文名":
                    ch["name_cn"] = item.get("value", "")
                    break
            else:
                ch["name_cn"] = ""
        except Exception as e:
            logger.warning(f"  角色 {cid} 详情获取失败: {e}")
            ch["collects"] = 0

    save_json(char_list, cache_file)
    return char_list


# ── Step 4: 汇总输出 ──

def build_final_outputs(anime_list, char_list):
    """生成最终的结构化数据：

    1. 角色列表（按 collects 降序）
    2. 番剧-角色映射（每部番剧的主角/配角列表）
    3. 汇总 markdown 报告
    """
    # 按收藏排序
    sorted_chars = sorted(char_list, key=lambda x: x.get("collects", 0), reverse=True)
    save_json(sorted_chars, "characters_ranked.json")

    # 番剧→角色映射
    anime_char_map = {}  # type: Dict[int, dict]
    for anime in anime_list:
        sid = anime["id"]
        anime_char_map[sid] = {
            "subject_id": sid,
            "name": anime.get("name", ""),
            "name_cn": anime.get("name_cn", ""),
            "rank": anime.get("rating", {}).get("rank"),
            "score": anime.get("rating", {}).get("score"),
            "main_characters": [],
            "supporting_characters": [],
        }

    for ch in sorted_chars:
        for rel in ch.get("relations", []):
            sid = rel["subject_id"]
            if sid not in anime_char_map:
                continue
            entry = {
                "character_id": ch["id"],
                "name": ch.get("name", ""),
                "name_cn": ch.get("name_cn", ""),
                "collects": ch.get("collects", 0),
                "relation": rel.get("relation", ""),
            }
            if rel.get("relation") == "主角":
                anime_char_map[sid]["main_characters"].append(entry)
            else:
                anime_char_map[sid]["supporting_characters"].append(entry)

    anime_char_list = sorted(anime_char_map.values(), key=lambda x: x.get("rank") or 9999)
    save_json(anime_char_list, "anime_character_map.json")

    # 主角子集
    main_chars = [ch for ch in sorted_chars if any(
        r.get("relation") == "主角" for r in ch.get("relations", [])
    )]
    save_json(main_chars, "main_characters_ranked.json")

    return sorted_chars, anime_char_list, main_chars


def generate_summary(anime_list, sorted_chars, anime_char_list, main_chars):
    lines = [
        "# Bangumi 数据采集汇总\n",
        f"采集时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n",
        "## 概览\n",
        f"| 指标 | 数量 |",
        f"|------|------|",
        f"| 番剧数量 | {len(anime_list)} |",
        f"| 角色总数（去重） | {len(sorted_chars)} |",
        f"| 其中主角数量 | {len(main_chars)} |",
        "",
        "## 番剧 Top 50（按 Bangumi 排名）\n",
        "| # | ID | 名称 | 中文名 | 评分 | rank |",
        "|---|-----|------|--------|------|------|",
    ]
    for i, a in enumerate(anime_list[:50], 1):
        r = a.get("rating", {})
        lines.append(
            f"| {i} | {a['id']} | {a.get('name','')} "
            f"| {a.get('name_cn','')} | {r.get('score','N/A')} | {r.get('rank','N/A')} |"
        )
    lines.append(f"\n*完整列表: local_data/bangumi/top_anime.json*\n")

    lines.append("## 人气角色 Top 50（按收藏数）\n")
    lines.append("| # | ID | 名称 | 中文名 | 收藏数 | 所属番剧 | 角色类型 |")
    lines.append("|---|-----|------|--------|--------|----------|----------|")
    for i, ch in enumerate(sorted_chars[:50], 1):
        rels = ch.get("relations", [])
        subj = ", ".join(r["subject_name"] for r in rels[:2])
        if len(rels) > 2:
            subj += f" 等{len(rels)}部"
        rel_types = ", ".join(sorted(set(r.get("relation", "") for r in rels)))
        lines.append(
            f"| {i} | {ch['id']} | {ch.get('name','')} "
            f"| {ch.get('name_cn','')} | {ch.get('collects',0)} "
            f"| {subj} | {rel_types} |"
        )
    lines.append(f"\n*完整列表: local_data/bangumi/characters_ranked.json*\n")

    lines.append("## 数据文件说明\n")
    lines.append("| 文件 | 说明 |")
    lines.append("|------|------|")
    lines.append("| `top_anime.json` | Top 300 番剧完整数据 |")
    lines.append("| `characters_ranked.json` | 所有角色（按收藏数排序），含番剧关联 |")
    lines.append("| `main_characters_ranked.json` | 仅主角（按收藏数排序） |")
    lines.append("| `anime_character_map.json` | 番剧→角色映射（每部番剧的主角/配角列表） |")

    summary_path = INFO_DIR / "bangumi_summary.md"
    with open(summary_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    logger.info(f"汇总已保存: {summary_path}")


def main():
    client = BangumiClient()
    logger.info("=" * 60)
    logger.info("Bangumi 数据采集开始")
    logger.info("=" * 60)

    # Step 1
    logger.info("\n[Step 1/4] 获取人气 Top 300 番剧")
    anime_list = fetch_top_anime(client, top_n=300)

    # Step 2
    logger.info("\n[Step 2/4] 从番剧获取角色 & 建立关联")
    char_list = fetch_characters_from_anime(client, anime_list)

    # Step 3
    logger.info("\n[Step 3/4] 补充角色详情 (collects / name_cn / gender)")
    char_list = enrich_characters(client, char_list)

    # Step 4
    logger.info("\n[Step 4/4] 汇总输出")
    sorted_chars, anime_char_list, main_chars = build_final_outputs(anime_list, char_list)
    generate_summary(anime_list, sorted_chars, anime_char_list, main_chars)

    logger.info("\n" + "=" * 60)
    logger.info("采集完成!")
    logger.info(f"  番剧: {len(anime_list)} 部")
    logger.info(f"  角色(全部): {len(sorted_chars)} 个")
    logger.info(f"  角色(主角): {len(main_chars)} 个")
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
