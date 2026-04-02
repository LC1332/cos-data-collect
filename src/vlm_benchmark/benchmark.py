"""VLM Cosplay 角色识别 Benchmark。

从 characters_ranked.json 中选取 rank=100,200,...,1000 的角色，
搜索每个角色的 1 张 cosplay 图，然后用多个 VLM 模型进行 cosplay 角色识别，
对比识别结果与 ground truth，生成评测报告。
"""

import json
import logging
import os
import shutil
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from better_bing_image_downloader import downloader as bing_downloader
from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from src.vlm_benchmark.vlm_clients import (
    MODEL_CONFIGS,
    recognize_cosplay,
    list_available_models,
)
from src.cosplay_analysis.compose_grid import compose_grid
from src.cosplay_analysis.vlm_client import (
    get_gemini_client,
    analyze_cosplay,
    get_correct_indices,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

DATA_DIR = PROJECT_ROOT / "local_data" / "bangumi"
BENCHMARK_DIR = PROJECT_ROOT / "local_data" / "vlm_benchmark"
BENCHMARK_DIR.mkdir(parents=True, exist_ok=True)
INFO_DIR = PROJECT_ROOT / "information"
INFO_DIR.mkdir(parents=True, exist_ok=True)

TARGET_RANKS = list(range(100, 1100, 100))
MAX_FALLBACK = 4
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}


# ── 角色选取 ──────────────────────────────────────────────────────

def load_characters_ranked() -> List[dict]:
    path = DATA_DIR / "characters_ranked.json"
    if not path.exists():
        raise FileNotFoundError(f"角色数据不存在: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def get_candidates_for_rank(
    characters: List[dict], target_rank: int,
) -> List[dict]:
    """返回 target_rank 及其 +1~+MAX_FALLBACK 的候选角色列表。"""
    candidates = []
    idx = target_rank - 1
    for offset in range(MAX_FALLBACK + 1):
        probe = idx + offset
        if probe >= len(characters):
            break
        ch = characters[probe].copy()
        ch["rank"] = target_rank + offset
        candidates.append(ch)
    return candidates


def _get_bangumi_name(character: dict) -> str:
    relations = character.get("relations", [])
    for r in relations:
        if r.get("relation") == "主角":
            return r["subject_name"]
    return relations[0]["subject_name"] if relations else ""


# ── Cosplay 图片搜索 ─────────────────────────────────────────────

def _get_brief_for_character(character: dict) -> Tuple[str, str]:
    """尝试从 brief_names 缓存中获取简称，否则用原名。"""
    char_id = str(character["id"])
    name_cn = character.get("name_cn", "")
    name = character.get("name", "")
    bangumi = _get_bangumi_name(character)

    for cache_file in (BENCHMARK_DIR.parent / "brief_names").glob("brief_names_*.json"):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                cache_data = json.load(f)
            for item in cache_data:
                if str(item.get("char_id")) == char_id:
                    return (
                        item.get("brief_name", name_cn or name),
                        item.get("brief_bangumi", bangumi),
                    )
        except Exception:
            continue

    return (name_cn or name, bangumi)


VLM_VERIFY_MODEL = "gemini-3-flash-preview"


def _download_original_image(character: dict) -> Optional[Path]:
    """从 Bangumi 下载角色原图。"""
    char_id = character["id"]
    orig_dir = BENCHMARK_DIR / "originals"
    orig_dir.mkdir(parents=True, exist_ok=True)

    existing = list(orig_dir.glob(f"{char_id}.*"))
    if existing:
        return existing[0]

    # 尝试本地 character_images
    char_img_dir = DATA_DIR / "character_images"
    for sz in ["large", "medium", "grid", "small"]:
        p = char_img_dir / f"{char_id}_{sz}.jpg"
        if p.exists():
            dst = orig_dir / f"{char_id}.jpg"
            shutil.copy2(p, dst)
            return dst

    # 从 Bangumi CDN 下载
    images = character.get("images") or {}
    for sz in ["large", "medium", "grid", "small"]:
        url = images.get(sz)
        if not url:
            continue
        dst = orig_dir / f"{char_id}.jpg"
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "cos-data-collect/1.0"}
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                dst.write_bytes(resp.read())
            logger.info(f"  原图已下载: {dst.name}")
            return dst
        except Exception as e:
            logger.warning(f"  原图下载失败 ({sz}): {e}")
    return None


def _bing_search_images(query: str, limit: int = 5) -> List[Path]:
    """Bing 搜索图片，返回临时路径列表。"""
    results: List[Path] = []
    with tempfile.TemporaryDirectory() as tmp_dir:
        try:
            bing_downloader(
                query=query,
                limit=limit,
                output_dir=tmp_dir,
                adult_filter_off=False,
                force_replace=False,
                timeout=30,
                verbose=False,
            )
        except Exception as e:
            logger.error(f"  Bing 搜索失败: {e}")
            return []

        found = sorted(
            p for p in Path(tmp_dir).rglob("*")
            if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES
        )
        # 复制到持久化目录（临时目录出函数就没了）
        persist_dir = BENCHMARK_DIR / "search_tmp"
        persist_dir.mkdir(parents=True, exist_ok=True)
        for p in found[:limit]:
            dst = persist_dir / f"{int(time.time()*1000)}_{p.name}"
            shutil.copy2(p, dst)
            results.append(dst)
    return results


def search_cosplay_image(
    character: dict,
    gemini_client=None,
) -> Optional[Path]:
    """完整管线：Bing 搜 5 张 → 拼 grid → VLM 鉴定 → 取通过的第一张。"""
    char_id = character["id"]
    out_dir = BENCHMARK_DIR / "images"
    out_dir.mkdir(parents=True, exist_ok=True)

    # 检查缓存
    existing = list(out_dir.glob(f"{char_id}.*"))
    if existing:
        logger.info(f"  已有验证后的 cosplay 图: {existing[0].name}")
        return existing[0]

    # 已有 cosplay_images 管线的结果可直接复用
    existing_cosplay = PROJECT_ROOT / "local_data" / "cosplay_images" / str(char_id)
    if existing_cosplay.exists():
        result_file = existing_cosplay / "result.json"
        if result_file.exists():
            result = json.loads(result_file.read_text(encoding="utf-8"))
            if result.get("any_correct"):
                # 取 brief_search 或 fallback_search 中第一张 correct 的图
                for stage in ["brief_search", "fallback_search"]:
                    info = result.get(stage)
                    if not info:
                        continue
                    for idx in info.get("correct_indices", []):
                        img_name = info["images"][idx]
                        src = existing_cosplay / img_name
                        if src.exists():
                            dst = out_dir / f"{char_id}{src.suffix}"
                            shutil.copy2(src, dst)
                            logger.info(f"  从已验证数据复制: {img_name}")
                            return dst

    # ── 完整管线 ──
    name_cn = character.get("name_cn", "")
    name = character.get("name", "")
    bangumi = _get_bangumi_name(character)
    char_label = name_cn or name

    original_img = _download_original_image(character)
    if not original_img:
        logger.warning(f"  无原图，跳过 VLM 验证")

    brief_name, brief_bangumi = _get_brief_for_character(character)

    for attempt, query in enumerate([
        f"{brief_name} cosplay {brief_bangumi}",
        f"{name_cn or name} {bangumi} cosplay coser",
    ]):
        attempt_label = "brief" if attempt == 0 else "fallback"
        logger.info(f'  搜索 ({attempt_label}): "{query}"')
        candidates = _bing_search_images(query, limit=5)
        if not candidates:
            logger.info(f"  {attempt_label} 无搜索结果")
            continue

        # VLM 验证
        correct_indices = list(range(len(candidates)))  # 默认全部通过（无 VLM 时）
        if original_img and gemini_client:
            grid_path = BENCHMARK_DIR / "grids" / f"{char_id}_{attempt_label}.jpg"
            grid_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                compose_grid(original_img, candidates, grid_path)
                vlm_result = analyze_cosplay(
                    gemini_client, grid_path,
                    character_name=char_label,
                    bangumi_name=brief_bangumi or bangumi,
                    num_pics=len(candidates),
                    model=VLM_VERIFY_MODEL,
                )
                correct_indices = get_correct_indices(vlm_result, len(candidates))
                logger.info(
                    f"  VLM 鉴定 ({attempt_label}): "
                    f"{len(correct_indices)}/{len(candidates)} 通过"
                )
            except Exception as e:
                logger.error(f"  VLM 鉴定失败: {e}，跳过验证")
                correct_indices = list(range(len(candidates)))
            finally:
                grid_path.unlink(missing_ok=True)

        if correct_indices:
            src = candidates[correct_indices[0]]
            ext = src.suffix.lower()
            if ext == ".jpeg":
                ext = ".jpg"
            dst = out_dir / f"{char_id}{ext}"
            shutil.copy2(src, dst)
            logger.info(f"  ✓ 选定: {dst.name}")
            # 清理临时搜索文件
            for c in candidates:
                c.unlink(missing_ok=True)
            return dst

        for c in candidates:
            c.unlink(missing_ok=True)

    logger.warning(f"  未搜索到有效 cosplay 图片")
    return None


# ── VLM 评测 ─────────────────────────────────────────────────────

def run_vlm_evaluation(
    test_samples: List[dict],
    models: Optional[List[str]] = None,
    delay: float = 2.0,
) -> Dict[str, List[dict]]:
    """对每个测试样本，分别调用多个 VLM 模型进行识别。

    Returns:
        {model_name: [{'char_id':..., 'ground_truth':..., 'prediction':..., ...}, ...]}
    """
    if models is None:
        models = list_available_models()
    if not models:
        raise ValueError("没有可用的 VLM 模型（请检查 .env 配置）")

    logger.info(f"评测模型: {models}")
    results: Dict[str, List[dict]] = {m: [] for m in models}

    for model_name in models:
        logger.info(f"\n{'='*50}")
        logger.info(f"模型: {model_name}")
        logger.info(f"{'='*50}")

        for i, sample in enumerate(test_samples):
            char_id = sample["char_id"]
            image_path = sample["image_path"]
            gt_char = sample["gt_character_name"]
            gt_bangumi = sample["gt_bangumi_name"]

            logger.info(
                f"  [{i+1}/{len(test_samples)}] Rank {sample['rank']}: "
                f"{gt_char} ({gt_bangumi})"
            )

            prediction = recognize_cosplay(image_path, model_name)

            entry = {
                "char_id": char_id,
                "rank": sample["rank"],
                "gt_character_name": gt_char,
                "gt_bangumi_name": gt_bangumi,
                "image": str(image_path),
                "prediction": prediction,
                "pred_character": prediction.get("character_name", ""),
                "pred_bangumi": prediction.get("bangumi_name", ""),
            }
            results[model_name].append(entry)

            cache_path = BENCHMARK_DIR / "results" / model_name.replace("/", "_")
            cache_path.mkdir(parents=True, exist_ok=True)
            (cache_path / f"{char_id}.json").write_text(
                json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8"
            )

            if i < len(test_samples) - 1:
                time.sleep(delay)

    return results


# ── 评分 ─────────────────────────────────────────────────────────

def _normalize(s: str) -> str:
    """粗粒度归一化：小写、去空格和标点。"""
    import re
    s = s.lower().strip()
    s = re.sub(r"[·・\-\s\u3000]", "", s)
    return s


def _fuzzy_match(pred: str, gt: str) -> bool:
    """模糊匹配：pred 包含 gt 或 gt 包含 pred（归一化后）。"""
    p, g = _normalize(pred), _normalize(gt)
    if not p or not g:
        return False
    return p in g or g in p


def evaluate_results(results: Dict[str, List[dict]]) -> Dict[str, dict]:
    """对每个模型计算角色识别和番剧识别的准确率。"""
    metrics: Dict[str, dict] = {}

    for model_name, entries in results.items():
        char_correct = 0
        bangumi_correct = 0
        total = len(entries)
        details = []

        for e in entries:
            gt_char = e["gt_character_name"]
            gt_bangumi = e["gt_bangumi_name"]
            pred_char = e.get("pred_character", "")
            pred_bangumi = e.get("pred_bangumi", "")

            char_match = _fuzzy_match(pred_char, gt_char)
            bangumi_match = _fuzzy_match(pred_bangumi, gt_bangumi)

            if char_match:
                char_correct += 1
            if bangumi_match:
                bangumi_correct += 1

            details.append({
                "rank": e["rank"],
                "gt_character": gt_char,
                "gt_bangumi": gt_bangumi,
                "pred_character": pred_char,
                "pred_bangumi": pred_bangumi,
                "char_match": char_match,
                "bangumi_match": bangumi_match,
            })

        metrics[model_name] = {
            "total": total,
            "char_correct": char_correct,
            "bangumi_correct": bangumi_correct,
            "char_accuracy": char_correct / total if total else 0,
            "bangumi_accuracy": bangumi_correct / total if total else 0,
            "details": details,
        }

    return metrics


# ── 报告生成 ─────────────────────────────────────────────────────

def generate_report(
    metrics: Dict[str, dict],
    results: Dict[str, List[dict]],
    test_samples: List[dict],
):
    """生成 Markdown 格式的 benchmark 报告。"""
    lines = [
        "# VLM Cosplay 角色识别 Benchmark 报告\n",
        f"生成时间: {time.strftime('%Y-%m-%d %H:%M:%S')}\n",
        f"测试样本数: {len(test_samples)}\n",
        f"测试模型: {', '.join(metrics.keys())}\n",
        "---\n",
    ]

    # 总览表格
    lines.append("## 模型评测总览\n")
    lines.append("| 模型 | 角色识别正确 | 角色准确率 | 番剧识别正确 | 番剧准确率 |")
    lines.append("|------|-------------|-----------|-------------|-----------|")
    for model_name, m in metrics.items():
        lines.append(
            f"| {model_name} "
            f"| {m['char_correct']}/{m['total']} "
            f"| {m['char_accuracy']:.0%} "
            f"| {m['bangumi_correct']}/{m['total']} "
            f"| {m['bangumi_accuracy']:.0%} |"
        )
    lines.append("")

    # 测试样本概览
    lines.append("## 测试样本\n")
    lines.append("| # | Rank | 角色名 | 番剧名 | 角色ID |")
    lines.append("|---|------|--------|--------|--------|")
    for i, s in enumerate(test_samples, 1):
        lines.append(
            f"| {i} | {s['rank']} "
            f"| {s['gt_character_name']} "
            f"| {s['gt_bangumi_name']} "
            f"| {s['char_id']} |"
        )
    lines.append("")

    # 每个模型的详细结果
    for model_name, m in metrics.items():
        lines.append(f"## {model_name} 详细结果\n")
        lines.append(
            f"角色准确率: **{m['char_accuracy']:.0%}** "
            f"({m['char_correct']}/{m['total']}) · "
            f"番剧准确率: **{m['bangumi_accuracy']:.0%}** "
            f"({m['bangumi_correct']}/{m['total']})\n"
        )

        for detail in m["details"]:
            rank = detail["rank"]
            char_mark = "✓" if detail["char_match"] else "✗"
            bangumi_mark = "✓" if detail["bangumi_match"] else "✗"
            lines.append(f"### Rank {rank}: {detail['gt_character']}\n")
            lines.append(f"| 字段 | Ground Truth | 预测 | 匹配 |")
            lines.append(f"|------|-------------|------|------|")
            lines.append(
                f"| 角色 | {detail['gt_character']} "
                f"| {detail['pred_character']} | {char_mark} |"
            )
            lines.append(
                f"| 番剧 | {detail['gt_bangumi']} "
                f"| {detail['pred_bangumi']} | {bangumi_mark} |"
            )
            lines.append("")

            entry = next(
                (e for e in results[model_name] if e["rank"] == rank), None
            )
            if entry and "prediction" in entry:
                pred = entry["prediction"]
                if "caption" in pred:
                    lines.append(f"**Caption:**\n> {pred['caption']}\n")
                if "analysis" in pred:
                    lines.append(f"**Analysis:**\n> {pred['analysis']}\n")

        lines.append("---\n")

    # 交叉对比矩阵
    lines.append("## 各模型 × 各样本 交叉对比\n")
    model_names = list(metrics.keys())
    header = "| Rank | Ground Truth |" + " | ".join(model_names) + " |"
    sep = "|------|-------------|" + " | ".join(["------"] * len(model_names)) + " |"
    lines.append(header)
    lines.append(sep)

    for s in test_samples:
        rank = s["rank"]
        gt = s["gt_character_name"]
        cells = []
        for mn in model_names:
            d = next(
                (x for x in metrics[mn]["details"] if x["rank"] == rank), None
            )
            if d:
                cm = "✓" if d["char_match"] else "✗"
                cells.append(f"{d['pred_character']} {cm}")
            else:
                cells.append("N/A")
        lines.append(f"| {rank} | {gt} | " + " | ".join(cells) + " |")
    lines.append("")

    report_path = INFO_DIR / "vlm_benchmark_report.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    logger.info(f"报告已保存: {report_path}")

    all_results = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "test_samples": [
            {k: v for k, v in s.items() if k != "image_path"}
            for s in test_samples
        ],
        "metrics": {
            mn: {k: v for k, v in m.items() if k != "details"}
            for mn, m in metrics.items()
        },
        "results": {
            mn: entries for mn, entries in results.items()
        },
    }
    results_path = BENCHMARK_DIR / "benchmark_results.json"
    results_path.write_text(
        json.dumps(all_results, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    logger.info(f"完整结果已保存: {results_path}")

    return report_path


# ── 主流程 ────────────────────────────────────────────────────────

def run_benchmark(
    models: Optional[List[str]] = None,
    delay: float = 2.0,
    skip_search: bool = False,
):
    """完整 benchmark 流程。

    Args:
        models: 要测试的模型列表，None 则使用所有可用模型
        delay: 每次 VLM 调用间隔秒数
        skip_search: 跳过图片搜索（使用已有图片）
    """
    logger.info("=" * 60)
    logger.info("VLM Cosplay 识别 Benchmark")
    logger.info("=" * 60)

    characters = load_characters_ranked()
    logger.info(f"已加载 {len(characters)} 个角色")

    # 初始化 Gemini client 用于 cosplay 图片验证
    gemini_client = None
    if not skip_search:
        try:
            gemini_client = get_gemini_client()
            logger.info("Gemini VLM 客户端已初始化（用于 cosplay 图片验证）")
        except Exception as e:
            logger.warning(f"Gemini 初始化失败，将跳过 VLM 验证: {e}")

    # 对每个目标 rank，搜索 cosplay 图；搜不到则顺位 +1~+4
    test_samples: List[dict] = []
    for target in TARGET_RANKS:
        candidates = get_candidates_for_rank(characters, target)
        found_sample = False

        for ch in candidates:
            char_id = ch["id"]
            name_cn = ch.get("name_cn", "")
            name = ch.get("name", "")
            bangumi = _get_bangumi_name(ch)
            label = name_cn or name

            logger.info(
                f"Rank {ch['rank']} (目标 {target}): {label} ({bangumi}), id={char_id}"
            )

            if skip_search:
                img_dir = BENCHMARK_DIR / "images"
                existing = list(img_dir.glob(f"{char_id}.*")) if img_dir.exists() else []
                image_path = existing[0] if existing else None
            else:
                image_path = search_cosplay_image(ch, gemini_client=gemini_client)

            if image_path:
                test_samples.append({
                    "char_id": char_id,
                    "rank": ch["rank"],
                    "target_rank": target,
                    "gt_character_name": label,
                    "gt_bangumi_name": bangumi,
                    "image_path": str(image_path),
                })
                found_sample = True
                break
            else:
                logger.info(f"  未找到图片，尝试下一个候选")

        if not found_sample:
            logger.warning(f"Rank {target} 及 +{MAX_FALLBACK} 均未搜到 cosplay 图")

    logger.info(f"\n有效测试样本: {len(test_samples)}/{len(TARGET_RANKS)}")

    if not test_samples:
        logger.error("没有有效的测试样本，退出")
        return

    # VLM 评测
    results = run_vlm_evaluation(test_samples, models=models, delay=delay)

    # 评分
    metrics = evaluate_results(results)
    for model_name, m in metrics.items():
        logger.info(
            f"  {model_name}: 角色 {m['char_accuracy']:.0%}, "
            f"番剧 {m['bangumi_accuracy']:.0%}"
        )

    # 报告
    report_path = generate_report(metrics, results, test_samples)

    logger.info("=" * 60)
    logger.info(f"Benchmark 完成! 报告: {report_path}")
    logger.info("=" * 60)


# ── CLI ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="VLM Cosplay 识别 Benchmark")
    parser.add_argument(
        "--models", nargs="+", default=None,
        help=f"指定模型 (可选: {list(MODEL_CONFIGS.keys())})",
    )
    parser.add_argument(
        "--delay", type=float, default=2.0,
        help="VLM 调用间隔 (秒)",
    )
    parser.add_argument(
        "--skip-search", action="store_true",
        help="跳过图片搜索，使用已有图片",
    )
    parser.add_argument(
        "--list-models", action="store_true",
        help="列出可用模型并退出",
    )
    args = parser.parse_args()

    if args.list_models:
        available = list_available_models()
        print(f"已配置模型: {list(MODEL_CONFIGS.keys())}")
        print(f"API Key 可用: {available}")
        sys.exit(0)

    run_benchmark(
        models=args.models,
        delay=args.delay,
        skip_search=args.skip_search,
    )
