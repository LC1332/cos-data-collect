"""生成「角色原图 · z-image 生成图 · Gemini 认证 cos」对比 HTML 页面。

数据来源：
  - 原图: local_data/bangumi/character_images/{id}_{large|medium|...}.jpg
  - 生成图: local_data/generated_images/{id}.<ext> 或 generated_images/{id}/*.{jpg,png,...}
  - cos: local_data/cosplay_images/{id}/result.json 中 brief / fallback 的 correct_indices 对应文件

用法:
  python -m src.cosplay_compare.build_character_gen_cos_compare
  python -m src.cosplay_compare.build_character_gen_cos_compare --only-with-cos
  python -m src.cosplay_compare.build_character_gen_cos_compare --open  # macOS 下尝试打开

打开 local_data/character_gen_cos_compare.html 时，请从仓库根目录用 HTTP 服务访问，
或使用与 local_data/cosplay_gallery.html 相同的方式，以便相对路径图片可加载。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from html import escape
from pathlib import Path
from typing import List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOCAL_DATA = PROJECT_ROOT / "local_data"
CHAR_IMG_DIR = LOCAL_DATA / "bangumi" / "character_images"
GEN_DIR = LOCAL_DATA / "generated_images"
COS_DIR = LOCAL_DATA / "cosplay_images"

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}


def _find_original_image(char_id: int) -> Optional[Path]:
    for sz in ("large", "medium", "grid", "small"):
        p = CHAR_IMG_DIR / f"{char_id}_{sz}.jpg"
        if p.exists():
            return p
    return None


def _find_generated_image(char_id: int) -> Optional[Path]:
    if not GEN_DIR.is_dir():
        return None
    for ext in sorted(IMAGE_SUFFIXES):
        p = GEN_DIR / f"{char_id}{ext}"
        if p.is_file():
            return p
    sub = GEN_DIR / str(char_id)
    if sub.is_dir():
        found: List[Path] = []
        for f in sub.iterdir():
            if f.is_file() and f.suffix.lower() in IMAGE_SUFFIXES:
                found.append(f)
        if found:
            found.sort(key=lambda x: x.name.lower())
            return found[0]
    return None


def _discover_generated_char_ids() -> List[int]:
    if not GEN_DIR.is_dir():
        return []
    ids: set[int] = set()
    for p in GEN_DIR.iterdir():
        if p.is_file():
            stem = p.stem
            if stem.isdigit():
                ids.add(int(stem))
        elif p.is_dir() and p.name.isdigit():
            ids.add(int(p.name))
    return sorted(ids)


def _verified_cos_images(char_id: int) -> List[Tuple[Path, str]]:
    """返回 (绝对路径, 简短标签)。"""
    result_path = COS_DIR / str(char_id) / "result.json"
    if not result_path.is_file():
        return []
    try:
        data = json.loads(result_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []

    char_dir = COS_DIR / str(char_id)
    out: List[Tuple[Path, str]] = []
    for stage_key, label in (
        ("brief_search", "brief"),
        ("fallback_search", "fallback"),
    ):
        block = data.get(stage_key)
        if not isinstance(block, dict):
            continue
        images = block.get("images") or []
        correct = set(block.get("correct_indices") or [])
        for i in sorted(correct):
            if not isinstance(i, int) or not (0 <= i < len(images)):
                continue
            fname = images[i]
            fp = char_dir / fname
            if fp.is_file():
                pic_label = chr(ord("A") + i) if i < 5 else str(i + 1)
                out.append((fp, f"{label} pic_{pic_label}"))
    return out


def _empty_page_html(only_with_cos: bool, has_any_generated: bool) -> str:
    base = (
        "未在 <code>local_data/generated_images/</code> 下发现任何角色生成图。"
        "将图片命名为 <code>{角色ID}.png</code> 或放入 <code>{角色ID}/</code> 子目录后重新运行本脚本。"
    )
    if only_with_cos and has_any_generated:
        return (
            '<p class="empty-page">已启用「仅含认证 cos」筛选：当前在含生成图的角色中，'
            "没有任何角色存在至少一张 Gemini 认证 cos 图（或对应文件缺失）。"
            "可去掉 <code>--only-with-cos</code> 查看全部。</p>"
        )
    return f'<p class="empty-page">{base}</p>'


def _meta_for_char(char_id: int) -> Tuple[str, str]:
    """(标题用主名, 副标题一行)。"""
    result_path = COS_DIR / str(char_id) / "result.json"
    if result_path.is_file():
        try:
            data = json.loads(result_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
        else:
            name = data.get("name_cn") or data.get("name") or str(char_id)
            bangumi = data.get("bangumi_name") or ""
            sub = f"ID {char_id}" + (f" · {bangumi}" if bangumi else "")
            return str(name), sub
    return f"角色 {char_id}", f"ID {char_id}"


def build_html(*, only_with_cos: bool = False) -> str:
    all_gen_ids = _discover_generated_char_ids()
    if only_with_cos:
        char_ids = [cid for cid in all_gen_ids if _verified_cos_images(cid)]
    else:
        char_ids = list(all_gen_ids)
    rows_html: List[str] = []

    for cid in char_ids:
        title, meta_line = _meta_for_char(cid)
        orig = _find_original_image(cid)
        gen = _find_generated_image(cid)
        cos_items = _verified_cos_images(cid)

        def rel(p: Optional[Path]) -> str:
            if not p:
                return ""
            return os.path.relpath(p, LOCAL_DATA).replace(os.sep, "/")

        orig_r, gen_r = rel(orig), rel(gen)

        rows_html.append('<div class="card">')
        rows_html.append('<div class="hdr">')
        rows_html.append(f"<h2>{escape(title)}</h2>")
        rows_html.append(f'<span class="tag-id">ID {cid}</span>')
        rows_html.append("</div>")
        rows_html.append(f'<div class="meta">{escape(meta_line)}</div>')

        rows_html.append('<div class="compare-row">')

        # 原图
        rows_html.append('<div class="panel">')
        rows_html.append('<div class="panel-title">角色原图</div>')
        rows_html.append('<div class="img-box">')
        if orig_r:
            rows_html.append(
                f'<img src="{escape(orig_r)}" alt="原图" loading="lazy">'
            )
        else:
            rows_html.append('<div class="no-img">无本地原图</div>')
        rows_html.append("</div></div>")

        # 生成图
        rows_html.append('<div class="panel">')
        rows_html.append('<div class="panel-title">生成图 (z-image)</div>')
        rows_html.append('<div class="img-box">')
        if gen_r:
            rows_html.append(
                f'<img src="{escape(gen_r)}" alt="生成图" loading="lazy">'
            )
        else:
            rows_html.append('<div class="no-img">未找到生成图</div>')
        rows_html.append("</div></div>")

        # Cos
        rows_html.append('<div class="panel panel-cos">')
        rows_html.append('<div class="panel-title">真实 cos（Gemini 认证）</div>')
        if not cos_items:
            rows_html.append('<div class="no-cos">暂无认证 cos 或尚无 result.json</div>')
        else:
            rows_html.append('<div class="cos-strip">')
            for fp, tag in cos_items:
                r = rel(fp)
                rows_html.append('<div class="cos-cell">')
                rows_html.append(
                    f'<div class="img-box img-box-sm">'
                    f'<img src="{escape(r)}" alt="{escape(tag)}" loading="lazy">'
                    f"</div>"
                )
                rows_html.append(f'<div class="cos-tag">{escape(tag)}</div>')
                rows_html.append("</div>")
            rows_html.append("</div>")
        rows_html.append("</div>")

        rows_html.append("</div></div>")

    if only_with_cos:
        filter_note = (
            f"筛选：仅展示至少 1 张 Gemini 认证 cos · "
            f"命中 {len(char_ids)} / {len(all_gen_ids)} 个含生成图角色 · "
        )
    else:
        filter_note = ""
    stats = (
        f"{filter_note}"
        f"共 {len(char_ids)} 个角色{'（全部含生成图）' if not only_with_cos else ''} · "
        f"有原图 {sum(1 for i in char_ids if _find_original_image(i))} · "
        f"有认证 cos {sum(1 for i in char_ids if _verified_cos_images(i))}"
    )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>角色原图 · 生成图 · 认证 Cos 对比</title>
<style>
:root {{
  --bg:#0f0f0f; --card:#1a1a2e; --border:#2a2a3e; --text:#e0e0e0; --dim:#888;
  --accent:#667eea; --gen:#e8a838; --cos:#6fcf6f;
}}
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
  background:var(--bg); color:var(--text);
  padding:24px; max-width:1600px; margin:0 auto;
}}
h1 {{
  text-align:center; padding:20px 0; font-size:26px;
  background:linear-gradient(135deg,#667eea,#764ba2);
  -webkit-background-clip:text; -webkit-text-fill-color:transparent;
}}
.stats {{ text-align:center; color:var(--dim); margin-bottom:28px; font-size:14px; }}
.card {{
  background:var(--card); border-radius:12px; margin-bottom:22px;
  padding:20px; border:1px solid var(--border);
}}
.hdr {{ display:flex; align-items:center; gap:12px; flex-wrap:wrap; margin-bottom:6px; }}
.hdr h2 {{ font-size:18px; color:#fff; }}
.tag-id {{
  font-size:12px; color:var(--dim); border:1px solid var(--border);
  padding:2px 8px; border-radius:8px;
}}
.meta {{ font-size:12px; color:var(--dim); margin-bottom:14px; }}
.compare-row {{
  display:flex; gap:18px; flex-wrap:wrap; align-items:flex-start;
}}
.panel {{
  flex:1; min-width:220px; max-width:480px;
}}
.panel-cos {{ flex:1.4; min-width:280px; max-width:720px; }}
.panel-title {{
  font-size:13px; color:var(--dim); margin-bottom:8px;
  font-weight:600; letter-spacing:0.02em;
}}
.panel:nth-child(1) .panel-title {{ color:#c4a8ff; }}
.panel:nth-child(2) .panel-title {{ color:var(--gen); }}
.panel-cos .panel-title {{ color:var(--cos); }}
.img-box {{
  background:#111; border-radius:10px; border:2px solid #333;
  display:flex; align-items:center; justify-content:center;
  min-height:280px; padding:8px;
}}
.img-box img {{
  max-width:100%; max-height:360px; width:auto; height:auto;
  object-fit:contain; vertical-align:middle;
}}
.img-box-sm {{
  min-height:200px; max-width:220px; margin:0 auto;
}}
.img-box-sm img {{
  max-height:280px;
}}
.no-img {{
  color:#555; font-size:13px; padding:40px 16px; text-align:center;
}}
.no-cos {{ color:#555; font-size:13px; padding:16px 0; }}
.cos-strip {{
  display:flex; flex-wrap:wrap; gap:14px; align-items:flex-start;
}}
.cos-cell {{ text-align:center; flex:0 0 auto; }}
.cos-tag {{ font-size:11px; color:var(--dim); margin-top:6px; max-width:220px; }}
.empty-page {{
  text-align:center; color:var(--dim); padding:48px 16px; font-size:15px;
}}
.empty-page code {{ color:var(--accent); }}
</style>
</head>
<body>
<h1>角色原图 · 生成图 · 认证 Cos 对比</h1>
<p class="stats">{escape(stats)}</p>
{"".join(rows_html) if rows_html else _empty_page_html(only_with_cos, bool(all_gen_ids))}
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="生成角色 / 生成图 / cos 对比页")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=LOCAL_DATA / "character_gen_cos_compare.html",
        help="输出 HTML 路径",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="生成后尝试用 open(1) 打开（macOS）",
    )
    parser.add_argument(
        "--only-with-cos",
        action="store_true",
        help="只展示至少有一张 Gemini 认证 cos 图的角色（仍要求存在生成图）",
    )
    args = parser.parse_args()
    out: Path = args.output
    if not out.is_absolute():
        out = PROJECT_ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    html = build_html(only_with_cos=args.only_with_cos)
    out.write_text(html, encoding="utf-8")
    print(f"已写入: {out}", file=sys.stderr)
    if args.open and sys.platform == "darwin":
        subprocess.run(["open", str(out)], check=False)


if __name__ == "__main__":
    main()
