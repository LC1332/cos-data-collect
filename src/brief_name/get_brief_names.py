"""获取角色和番剧的简称。

从 characters_ranked.json 中读取角色信息，调用 LLM 获取角色名和番剧名的简称，
结果缓存到 local_data/brief_names/ 并输出实验报告到 information/。
"""

import json
import logging
import os
import random
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.brief_name.llm_client import get_llm_client, chat_completion_json

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

DATA_DIR = PROJECT_ROOT / "local_data" / "bangumi"
CACHE_DIR = PROJECT_ROOT / "local_data" / "brief_names"
INFO_DIR = PROJECT_ROOT / "information"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
INFO_DIR.mkdir(parents=True, exist_ok=True)

def _model_slug(model: str) -> str:
    """将模型名转为安全的文件名片段。"""
    return model.replace("/", "_").replace(" ", "_")

SYSTEM_PROMPT = """\
你是一个动漫/番剧领域的专家，熟悉中日两国的ACG文化。
你的任务是为给定的角色和其所属番剧提供大家最常用的简称。
请严格按照要求的 JSON 格式返回结果。"""

USER_PROMPT_TEMPLATE = """\
请根据给定的角色和番剧信息，以JSON形式向我返回大家最能接受的角色简称和番剧简称（如有）。

简称映射的例子:
"攻殻機動隊 S.A.C. 2nd GIG" --> "攻壳机动队"
"惣流·明日香·兰格雷" --> "明日香"
"长门有希" --> "长门有希"
"新世纪福音战士" --> "EVA"
"阿尔托莉雅·潘德拉贡" --> "阿尔托莉雅"
"艾伦·耶格尔" --> "艾伦"
"初音未来" --> "初音未来"
（如果有中文字使用简体中文）

需要获取简称的角色信息如下：
- **角色中文名**: {name_cn}
- 角色日文名（辅助信息）: {name}
- 角色ID: {char_id}
- 出场番剧:
{relations_text}

以JSON形式返回你的分析和结果，并包含以下所有字段（按顺序逐步思考）：
- decide_if_brief: 简单分析是否需要对角色和番剧进行简称，如果原来的番剧名或者角色名已经足够简洁（五个中文字以内就肯定不用继续缩写了），可以直接沿用
- analysis: 大家最常用的简称是哪些，大家一般怎么称呼这个番剧和角色，使用简称的角色×番剧是不是能够基本定位到这个角色
- brief_name: 角色的简称（字符串）
- brief_bangumi: 该角色最具代表性的番剧的简称（字符串）

请只返回JSON，不要添加其他内容。"""


def load_characters(top_n: int = 1000) -> List[dict]:
    path = DATA_DIR / "characters_ranked.json"
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return data[:top_n]


def _cache_path(model: str) -> Path:
    return CACHE_DIR / f"brief_names_{_model_slug(model)}.json"


def load_cache(model: str) -> Dict[str, dict]:
    path = _cache_path(model)
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {str(item["char_id"]): item for item in data}
    return {}


def save_cache(cache: Dict[str, dict], model: str):
    path = _cache_path(model)
    items = sorted(cache.values(), key=lambda x: x.get("char_id", 0))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)
    logger.info(f"缓存已保存: {path} ({len(items)} 条)")


def format_relations(relations: List[dict]) -> str:
    lines = []
    for r in relations:
        lines.append(f"  - 番剧名: {r['subject_name']} (ID: {r['subject_id']}, 角色类型: {r.get('relation', '未知')})")
    return "\n".join(lines) if lines else "  (无番剧信息)"


def get_brief_name_for_character(
    client, character: dict, model: Optional[str] = None,
) -> Optional[dict]:
    """为单个角色调用 LLM 获取简称。"""
    char_id = character["id"]
    name = character.get("name", "")
    name_cn = character.get("name_cn", "")
    relations = character.get("relations", [])

    user_prompt = USER_PROMPT_TEMPLATE.format(
        name=name,
        name_cn=name_cn,
        char_id=char_id,
        relations_text=format_relations(relations),
    )

    try:
        result = chat_completion_json(client, SYSTEM_PROMPT, user_prompt, model=model)
        result["char_id"] = char_id
        result["original_name"] = name
        result["original_name_cn"] = name_cn
        result["original_relations"] = relations
        return result
    except Exception as e:
        logger.error(f"角色 {char_id} ({name_cn or name}) LLM 调用失败: {e}")
        return None


def run_experiment(
    n_samples: int = 5,
    seed: int = 42,
    model: Optional[str] = None,
    base_url: Optional[str] = None,
):
    """在 top 1000 角色中随机选取 n_samples 个进行实验。"""
    client = get_llm_client(base_url=base_url)
    model = model or os.getenv("CUSTOM_MODEL", "deepseek-chat")
    characters = load_characters(top_n=1000)
    cache = load_cache(model)

    random.seed(seed)
    sampled = random.sample(characters, min(n_samples, len(characters)))

    logger.info(f"模型: {model}")
    logger.info(f"选取 {len(sampled)} 个角色进行实验:")
    for ch in sampled:
        logger.info(f"  - {ch.get('name_cn') or ch.get('name')} (id={ch['id']})")

    results = []
    for i, ch in enumerate(sampled):
        char_id_str = str(ch["id"])

        if char_id_str in cache:
            logger.info(f"[{i+1}/{len(sampled)}] 使用缓存: {ch.get('name_cn') or ch.get('name')}")
            results.append(cache[char_id_str])
            continue

        logger.info(f"[{i+1}/{len(sampled)}] 调用 LLM: {ch.get('name_cn') or ch.get('name')}")
        result = get_brief_name_for_character(client, ch, model=model)

        if result:
            cache[char_id_str] = result
            results.append(result)
            save_cache(cache, model)

        if i < len(sampled) - 1:
            time.sleep(1)

    generate_report(results, sampled, model=model)
    return results


def generate_report(
    results: List[dict],
    sampled_characters: List[dict],
    model: Optional[str] = None,
):
    """生成实验报告到 information/ 目录。"""
    model = model or os.getenv("CUSTOM_MODEL", "deepseek-chat")
    lines = [
        "# LLM 角色简称实验报告\n",
        f"生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n",
        f"模型: {model}",
        f"样本数量: {len(results)} (从 top 1000 角色中随机抽取)\n",
        "---\n",
    ]

    for i, r in enumerate(results, 1):
        name = r.get("original_name", "")
        name_cn = r.get("original_name_cn", "")
        brief_name = r.get("brief_name", "N/A")
        brief_bangumi = r.get("brief_bangumi", "N/A")
        decide_if_brief = r.get("decide_if_brief", "N/A")
        analysis = r.get("analysis", "N/A")
        relations = r.get("original_relations", [])

        lines.append(f"## {i}. {name_cn or name}\n")
        lines.append(f"| 字段 | 值 |")
        lines.append(f"|------|------|")
        lines.append(f"| 角色ID | {r.get('char_id', 'N/A')} |")
        lines.append(f"| 日文名 | {name} |")
        lines.append(f"| 中文名 | {name_cn} |")
        lines.append(f"| **角色简称** | **{brief_name}** |")
        lines.append(f"| **番剧简称** | **{brief_bangumi}** |")
        lines.append(f"")

        if relations:
            lines.append("**出场番剧:**\n")
            for rel in relations:
                lines.append(f"- {rel['subject_name']} ({rel.get('relation', '')})")
            lines.append("")

        lines.append(f"**是否需要简称:**\n")
        lines.append(f"> {decide_if_brief}\n")
        lines.append(f"**分析:**\n")
        lines.append(f"> {analysis}\n")
        lines.append("---\n")

    # 汇总表格
    lines.append("## 汇总\n")
    lines.append("| # | 原名 | 中文名 | 角色简称 | 番剧简称 |")
    lines.append("|---|------|--------|----------|----------|")
    for i, r in enumerate(results, 1):
        lines.append(
            f"| {i} | {r.get('original_name', '')} "
            f"| {r.get('original_name_cn', '')} "
            f"| {r.get('brief_name', 'N/A')} "
            f"| {r.get('brief_bangumi', 'N/A')} |"
        )
    lines.append("")

    report_path = INFO_DIR / f"brief_name_experiment_{_model_slug(model)}.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    logger.info(f"实验报告已保存: {report_path}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="获取角色和番剧简称")
    parser.add_argument("--model", type=str, default=None, help="LLM 模型名称")
    parser.add_argument("--base-url", type=str, default=None, help="LLM API base URL")
    parser.add_argument("--samples", type=int, default=5, help="采样数量")
    parser.add_argument("--seed", type=int, default=42, help="随机种子")
    args = parser.parse_args()

    run_experiment(
        n_samples=args.samples,
        seed=args.seed,
        model=args.model,
        base_url=args.base_url,
    )
