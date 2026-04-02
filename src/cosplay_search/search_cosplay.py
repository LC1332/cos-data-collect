"""Cosplay 图片搜索 + VLM 验证流水线。

对每个角色依次：
1. 调用 LLM 获取角色/番剧简称（有缓存则跳过）
2. 使用 "{简化角色名} cosplay {简化番剧名}" 搜索 5 张图片
3. 调用 Gemini VLM 验证哪些是正确 cosplay
4. 若全部未通过，用 "{原角色名} {原剧名} cosplay coser" 补充下载 5 张再验证

存储结构（平铺，无子目录）:
  local_data/cosplay_images/{char_id}/
    {char_id}_1.jpg ~ {char_id}_5.jpg      brief 搜索结果
    {char_id}_6.jpg ~ {char_id}_10.jpg     fallback 补充（如需）
    vlm_brief.json                          VLM 分析结果
    vlm_fallback.json                       fallback VLM 分析结果（如需）
    result.json                             整体结果
"""

import json
import logging
import os
import shutil
import sys
import tempfile
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
    load_cache as load_brief_cache,
    save_cache as save_brief_cache,
)
from src.cosplay_analysis.compose_grid import compose_grid
from src.cosplay_analysis.vlm_client import (
    get_gemini_client,
    analyze_cosplay,
    count_correct,
    get_correct_indices,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

DATA_DIR = PROJECT_ROOT / "local_data" / "bangumi"
CHAR_IMG_DIR = DATA_DIR / "character_images"
COSPLAY_DIR = PROJECT_ROOT / "local_data" / "cosplay_images"
PROGRESS_FILE = PROJECT_ROOT / "local_data" / "cosplay_search_progress.json"

BRIEF_MODEL = "gpt-5-mini"
VLM_MODEL = "gemini-3-flash-preview"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}


# ── 工具函数 ───────────────────────────────────────────────────────

def _find_original_image(char_id: int) -> Optional[Path]:
    for sz in ["large", "medium", "grid", "small"]:
        p = CHAR_IMG_DIR / f"{char_id}_{sz}.jpg"
        if p.exists():
            return p
    return None


def _char_dir(char_id: int) -> Path:
    return COSPLAY_DIR / str(char_id)


def _get_cosplay_images(char_id: int) -> List[Path]:
    """获取已有的 cosplay 图片（{char_id}_N.ext），按编号排序。"""
    d = _char_dir(char_id)
    if not d.exists():
        return []
    prefix = f"{char_id}_"
    imgs = []
    for p in d.iterdir():
        if (p.is_file()
                and p.suffix.lower() in IMAGE_SUFFIXES
                and p.stem.startswith(prefix)):
            try:
                int(p.stem[len(prefix):])
                imgs.append(p)
            except ValueError:
                pass
    imgs.sort(key=lambda p: int(p.stem[len(prefix):]))
    return imgs


def _next_index(char_id: int) -> int:
    """下一个可用的图片编号。"""
    imgs = _get_cosplay_images(char_id)
    if not imgs:
        return 1
    prefix = f"{char_id}_"
    return max(int(p.stem[len(prefix):]) for p in imgs) + 1


def _download_and_rename(
    query: str, char_id: int, limit: int = 5,
) -> List[Path]:
    """Bing 搜索图片 → 重命名为 {char_id}_{idx}.jpg 存入角色目录。"""
    char_out = _char_dir(char_id)
    char_out.mkdir(parents=True, exist_ok=True)
    start_idx = _next_index(char_id)

    logger.info(f'  搜索: "{query}"')
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
            logger.error(f"  下载失败: {e}")
            return []

        tmp_imgs = sorted(
            p for p in Path(tmp_dir).rglob("*")
            if p.is_file() and p.suffix.lower() in IMAGE_SUFFIXES
        )

        saved: List[Path] = []
        for i, src in enumerate(tmp_imgs[:limit]):
            idx = start_idx + i
            ext = src.suffix.lower()
            if ext in (".jpeg",):
                ext = ".jpg"
            elif ext not in IMAGE_SUFFIXES:
                ext = ".jpg"
            dst = char_out / f"{char_id}_{idx}{ext}"
            shutil.move(str(src), str(dst))
            saved.append(dst)

    if saved:
        logger.info(f"  保存 {len(saved)} 张 (#{start_idx}~#{start_idx + len(saved) - 1})")
    else:
        logger.warning(f"  未搜到图片")
    return saved


def _get_bangumi_name(character: dict) -> str:
    relations = character.get("relations", [])
    for r in relations:
        if r.get("relation") == "主角":
            return r["subject_name"]
    return relations[0]["subject_name"] if relations else ""


# ── 简称 ──────────────────────────────────────────────────────────

def _get_brief(llm_client, character: dict, cache: Dict[str, dict]) -> Optional[dict]:
    char_id = str(character["id"])
    if char_id in cache:
        return cache[char_id]

    user_prompt = USER_PROMPT_TEMPLATE.format(
        name=character.get("name", ""),
        name_cn=character.get("name_cn", ""),
        char_id=character["id"],
        relations_text=format_relations(character.get("relations", [])),
    )
    try:
        result = chat_completion_json(llm_client, SYSTEM_PROMPT, user_prompt, model=BRIEF_MODEL)
        result["char_id"] = character["id"]
        result["original_name"] = character.get("name", "")
        result["original_name_cn"] = character.get("name_cn", "")
        result["original_relations"] = character.get("relations", [])
        cache[char_id] = result
        save_brief_cache(cache, BRIEF_MODEL)
        logger.info(f"  简称: {result.get('brief_name')} / {result.get('brief_bangumi')}")
        return result
    except Exception as e:
        logger.error(f"  简称获取失败: {e}")
        return None


# ── VLM 验证（使用临时 grid） ─────────────────────────────────────

def _vlm_verify(
    images: List[Path],
    original_img: Path,
    char_name: str,
    bangumi_name: str,
    gemini_client,
    char_id: int,
    label: str,
) -> dict:
    """构建临时网格图 → VLM 分析 → 删除网格 → 返回结果。"""
    char_out = _char_dir(char_id)
    info: dict = {
        "images": [p.name for p in images],
        "correct_count": 0,
        "correct_indices": [],
        "vlm_result": None,
    }
    if not images:
        return info

    grid_path = char_out / f"_tmp_grid.jpg"
    try:
        compose_grid(original_img, images, grid_path)
        vlm = analyze_cosplay(
            gemini_client, grid_path,
            character_name=char_name,
            bangumi_name=bangumi_name,
            num_pics=len(images),
            model=VLM_MODEL,
        )
        info["vlm_result"] = vlm
        info["correct_count"] = count_correct(vlm, len(images))
        info["correct_indices"] = get_correct_indices(vlm, len(images))

        vlm_path = char_out / f"vlm_{label}.json"
        vlm_path.write_text(
            json.dumps(vlm, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info(f"  VLM ({label}): {info['correct_count']}/{len(images)} 正确")
    except Exception as e:
        logger.error(f"  VLM 失败: {e}")
        info["vlm_error"] = str(e)
    finally:
        grid_path.unlink(missing_ok=True)

    return info


# ── 进度管理 ──────────────────────────────────────────────────────

def load_progress() -> dict:
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"completed": [], "failed": []}


def save_progress(progress: dict):
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)


# ── 主流水线 ──────────────────────────────────────────────────────

def run_pipeline(
    top_n: int = 10,
    start: int = 0,
    limit_per_char: int = 5,
    delay_between: float = 3.0,
    skip_completed: bool = True,
    enable_vlm: bool = True,
):
    """完整流水线：简称 → 搜索 → VLM 验证 → 补充回退。"""
    openai_url = os.getenv("CUSTOM_BASE_URL_OPENAI", "").strip()
    if not openai_url:
        raise ValueError("请在 .env 中配置 CUSTOM_BASE_URL_OPENAI")

    llm_client = get_llm_client(base_url=openai_url)
    gemini_client = get_gemini_client() if enable_vlm else None
    brief_cache = load_brief_cache(BRIEF_MODEL)
    progress = load_progress()
    characters = load_characters(top_n=top_n)[start:]

    logger.info("=" * 60)
    logger.info(f"Cosplay 流水线 (VLM={'ON' if enable_vlm else 'OFF'})")
    logger.info(f"角色范围: #{start+1}~#{start+len(characters)}, 每角色: {limit_per_char} 张")
    logger.info("=" * 60)

    results = []
    for i, ch in enumerate(characters):
        char_id = ch["id"]
        lbl = ch.get("name_cn") or ch.get("name", str(char_id))

        if skip_completed and char_id in progress.get("completed", []):
            logger.info(f"[{start+i+1}] 跳过: {lbl}")
            continue

        logger.info(f"[{start+i+1}] 处理: {lbl} (id={char_id})")
        char_out = _char_dir(char_id)
        char_out.mkdir(parents=True, exist_ok=True)

        original_img = _find_original_image(char_id)
        bangumi_name = _get_bangumi_name(ch)
        name_cn = ch.get("name_cn", "")
        name = ch.get("name", "")
        char_label = name_cn or name

        # Step 1: 简称
        brief = _get_brief(llm_client, ch, brief_cache)
        brief_name = brief.get("brief_name", char_label) if brief else char_label
        brief_bangumi = brief.get("brief_bangumi", "") if brief else ""

        result: dict = {
            "char_id": char_id,
            "name": name,
            "name_cn": name_cn,
            "bangumi_name": bangumi_name,
            "brief_name": brief_name,
            "brief_bangumi": brief_bangumi,
            "brief_search": None,
            "fallback_search": None,
            "any_correct": False,
        }

        # Step 2: Brief 搜索 + 下载
        query_brief = f"{brief_name} cosplay {brief_bangumi}"
        brief_imgs = _download_and_rename(query_brief, char_id, limit=limit_per_char)

        if enable_vlm and original_img and gemini_client and brief_imgs:
            brief_info = _vlm_verify(
                brief_imgs, original_img, char_label,
                brief_bangumi or bangumi_name, gemini_client, char_id, "brief",
            )
            brief_info["query"] = query_brief
            result["brief_search"] = brief_info

            if brief_info["correct_count"] > 0:
                result["any_correct"] = True
            else:
                # Step 3: 全部未通过 → fallback 补充下载
                logger.info(f"  Brief 全部未通过，补充 fallback 搜索")
                query_fb = f"{name_cn or name} {bangumi_name} cosplay coser"
                fb_imgs = _download_and_rename(query_fb, char_id, limit=limit_per_char)
                if fb_imgs:
                    fb_info = _vlm_verify(
                        fb_imgs, original_img, char_label,
                        bangumi_name, gemini_client, char_id, "fallback",
                    )
                    fb_info["query"] = query_fb
                    result["fallback_search"] = fb_info
                    if fb_info["correct_count"] > 0:
                        result["any_correct"] = True
        else:
            if not brief_imgs:
                brief_imgs = []
            result["brief_search"] = {
                "query": query_brief,
                "images": [p.name for p in brief_imgs],
                "vlm_skipped": not enable_vlm,
            }

        # 保存结果
        (char_out / "result.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        results.append(result)
        progress.setdefault("completed", []).append(char_id)
        save_progress(progress)

        if i < len(characters) - 1:
            logger.info(f"  等待 {delay_between}s ...")
            time.sleep(delay_between)

    correct = sum(1 for r in results if r.get("any_correct"))
    logger.info("=" * 60)
    logger.info(f"完成: {len(results)} 角色, {correct} 有正确 cosplay")
    logger.info("=" * 60)
    return results


# ── HTML 展示 ─────────────────────────────────────────────────────

def generate_html(top_n: int = 10):
    """生成 HTML 展示 cosplay 搜索 + VLM 验证结果。"""
    characters = load_characters(top_n=top_n)

    html_parts: List[str] = []
    _h = html_parts.append

    _h("<!DOCTYPE html><html lang='zh-CN'><head>")
    _h("<meta charset='UTF-8'>")
    _h("<meta name='viewport' content='width=device-width,initial-scale=1'>")
    _h(f"<title>Cosplay VLM 验证 - Top {top_n}</title>")
    _h("<style>")
    _h("""
:root { --bg:#0f0f0f; --card:#1a1a2e; --border:#2a2a3e; --text:#e0e0e0; --dim:#888; }
* { margin:0; padding:0; box-sizing:border-box; }
body { font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
       background:var(--bg); color:var(--text); padding:24px; max-width:1400px; margin:0 auto; }
h1 { text-align:center; padding:24px 0; font-size:28px;
     background:linear-gradient(135deg,#667eea,#764ba2);
     -webkit-background-clip:text; -webkit-text-fill-color:transparent; }
.stats { text-align:center; color:var(--dim); margin-bottom:24px; font-size:14px; }
.card { background:var(--card); border-radius:12px; margin-bottom:20px;
        padding:20px; border:1px solid var(--border); }
.hdr { display:flex; align-items:center; gap:12px; margin-bottom:10px; flex-wrap:wrap; }
.hdr h2 { font-size:18px; color:#fff; }
.meta { font-size:12px; color:var(--dim); }
.tag { display:inline-block; padding:2px 8px; border-radius:8px;
       font-size:11px; font-weight:bold; }
.tag-pass { background:#2d4a2d; color:#6fcf6f; }
.tag-fail { background:#4a2d2d; color:#cf6f6f; }
.tag-rank { background:linear-gradient(135deg,#667eea,#764ba2);
            color:#fff; padding:3px 10px; border-radius:12px; font-size:13px; }
.stage { margin-top:12px; }
.stage-hdr { font-size:13px; color:var(--dim); margin-bottom:6px; }
.stage-hdr em { color:#667eea; font-style:italic; }
.row { display:flex; gap:10px; overflow-x:auto; padding-bottom:6px; }
.cell { flex-shrink:0; text-align:center; }
.cell img { width:160px; height:220px; object-fit:contain;
            border-radius:8px; border:2px solid #333; background:#111;
            transition:transform .2s; cursor:pointer; }
.cell img:hover { transform:scale(1.08); }
.cell.orig img { border-color:#764ba2; }
.cell.ok img { border-color:#6fcf6f; }
.cell.fail img { border-color:#cf4f4f; }
.lbl { font-size:11px; color:var(--dim); margin-top:3px; }
.lbl .tick { color:#6fcf6f; font-weight:bold; }
.lbl .cross { color:#cf4f4f; }
.no-img { width:160px; height:220px; border-radius:8px; background:#1e1e30;
          display:flex; align-items:center; justify-content:center;
          color:#444; font-size:12px; border:2px dashed #333; }
.no-data { color:#555; font-size:13px; padding:12px 0; }
""")
    _h("</style></head><body>")
    _h("<h1>Cosplay 搜索 + VLM 验证结果</h1>")

    total_correct = 0
    total_with_result = 0
    for ch in characters:
        rf = _char_dir(ch["id"]) / "result.json"
        if rf.exists():
            total_with_result += 1
            r = json.loads(rf.read_text(encoding="utf-8"))
            if r.get("any_correct"):
                total_correct += 1

    _h(f'<p class="stats">Top {top_n} 角色 · 已处理 {total_with_result} · '
       f'{total_correct} 有正确 cosplay</p>')

    for rank, ch in enumerate(characters, 1):
        char_id = ch["id"]
        char_label = ch.get("name_cn") or ch.get("name", "")
        char_out = _char_dir(char_id)

        result_file = char_out / "result.json"
        result: dict = {}
        if result_file.exists():
            result = json.loads(result_file.read_text(encoding="utf-8"))

        original_img = _find_original_image(char_id)
        original_rel = (
            os.path.relpath(original_img, COSPLAY_DIR.parent) if original_img else ""
        )
        relations_str = ", ".join(
            r["subject_name"] for r in ch.get("relations", [])[:3]
        )
        any_correct = result.get("any_correct", False)

        _h('<div class="card">')
        _h('<div class="hdr">')
        _h(f'<span class="tag tag-rank">#{rank}</span>')
        _h(f'<h2>{char_label}</h2>')
        tc = "tag-pass" if any_correct else "tag-fail"
        tt = "✓ 有正确cos" if any_correct else "✗ 未通过"
        _h(f'<span class="tag {tc}">{tt}</span>')
        _h("</div>")
        _h(f'<div class="meta">{ch.get("name","")} · ID {char_id} · {relations_str}</div>')

        if not result:
            _h('<div class="no-data">尚未处理</div>')
            _h("</div>")
            continue

        for stage_key, stage_name in [
            ("brief_search", "Brief 搜索"),
            ("fallback_search", "Fallback 补充"),
        ]:
            info = result.get(stage_key)
            if not info:
                continue

            query = info.get("query", "")
            correct_set = set(info.get("correct_indices", []))
            img_names = info.get("images", [])
            n_correct = info.get("correct_count", 0)
            n_total = len(img_names)

            _h('<div class="stage">')
            _h(f'<div class="stage-hdr">{stage_name}: <em>{query}</em> · '
               f'{n_correct}/{n_total} 正确</div>')
            _h('<div class="row">')

            # 原角色图（仅 brief 行显示）
            if stage_key == "brief_search":
                _h('<div class="cell orig">')
                if original_rel:
                    _h(f'<img src="{original_rel}" alt="原角色" loading="lazy">')
                else:
                    _h('<div class="no-img">无原图</div>')
                _h('<div class="lbl">原角色</div></div>')

            for j, fname in enumerate(img_names):
                fpath = char_out / fname
                is_ok = j in correct_set
                cls = "cell ok" if is_ok else "cell fail"
                _h(f'<div class="{cls}">')
                if fpath.exists():
                    rel = os.path.relpath(fpath, COSPLAY_DIR.parent)
                    _h(f'<img src="{rel}" alt="{fname}" loading="lazy">')
                else:
                    _h('<div class="no-img">缺失</div>')
                mark = '<span class="tick">✓</span>' if is_ok else '<span class="cross">✗</span>'
                _h(f'<div class="lbl">{fname} {mark}</div>')
                _h("</div>")

            _h("</div>")  # row
            _h("</div>")  # stage

        _h("</div>")  # card

    _h("</body></html>")

    out_path = PROJECT_ROOT / "local_data" / "cosplay_gallery.html"
    out_path.write_text("\n".join(html_parts), encoding="utf-8")
    logger.info(f"HTML 已生成: {out_path}")
    return out_path


# ── CLI ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Cosplay 搜索 + VLM 验证流水线")
    parser.add_argument("--top-n", type=int, default=10, help="处理前 N 个角色")
    parser.add_argument("--start", type=int, default=0, help="从第几个角色开始（0-based）")
    parser.add_argument("--limit", type=int, default=5, help="每轮下载图片数")
    parser.add_argument("--delay", type=float, default=3.0, help="角色间延迟(秒)")
    parser.add_argument("--no-skip", action="store_true", help="不跳过已完成角色")
    parser.add_argument("--no-vlm", action="store_true", help="只下载不做 VLM")
    parser.add_argument("--html-only", action="store_true", help="仅生成 HTML")
    args = parser.parse_args()

    if args.html_only:
        generate_html(top_n=args.top_n)
    else:
        run_pipeline(
            top_n=args.top_n,
            start=args.start,
            limit_per_char=args.limit,
            delay_between=args.delay,
            skip_completed=not args.no_skip,
            enable_vlm=not args.no_vlm,
        )
        generate_html(top_n=args.top_n)
