"""生成「生成 cos 图 · 角色原图 · 合影」紧凑对比 HTML（每行两组）。

数据来源：
  - 生成图: local_data/generated_images/{id}.<ext> 或 generated_images/{id}/*.{jpg,png,...}
  - 原图: local_data/bangumi/character_images/{id}_{large|medium|grid|small}.jpg
  - 合影: local_data/group/ 下图片，文件名需能解析出角色 ID（见 _char_id_from_group_file）

用法:
  python -m src.cosplay_compare.build_gen_char_group_compare
  python -m src.cosplay_compare.build_gen_char_group_compare --open

打开输出的 HTML 时请从仓库根目录起 HTTP 服务，以便相对路径图片可加载。
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from html import escape
from pathlib import Path
from typing import List, Optional, Set

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOCAL_DATA = PROJECT_ROOT / "local_data"
CHAR_IMG_DIR = LOCAL_DATA / "bangumi" / "character_images"
GEN_DIR = LOCAL_DATA / "generated_images"
GROUP_DIR = LOCAL_DATA / "group"

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}


def _char_id_from_group_file(path: Path) -> Optional[int]:
    """从合影文件名解析角色 ID：纯数字 stem，或 stem 末尾段为数字（如 group_1211）。"""
    stem = path.stem.strip()
    if stem.isdigit():
        return int(stem)
    m = re.search(r"(?:^|_)(\d+)$", stem)
    if m:
        return int(m.group(1))
    return None


def _discover_group_char_ids() -> List[int]:
    if not GROUP_DIR.is_dir():
        return []
    seen: Set[int] = set()
    for p in GROUP_DIR.iterdir():
        if not p.is_file() or p.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        cid = _char_id_from_group_file(p)
        if cid is not None:
            seen.add(cid)
    return sorted(seen)


def _find_group_image(char_id: int) -> Optional[Path]:
    if not GROUP_DIR.is_dir():
        return None
    candidates: List[Path] = []
    for ext in sorted(IMAGE_SUFFIXES):
        p = GROUP_DIR / f"{char_id}{ext}"
        if p.is_file():
            candidates.append(p)
    for p in GROUP_DIR.iterdir():
        if not p.is_file() or p.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        if _char_id_from_group_file(p) == char_id:
            candidates.append(p)
    if not candidates:
        return None
    candidates.sort(key=lambda x: (x.name.lower(), str(x)))
    return candidates[0]


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


def _rel_to_local_data(p: Optional[Path]) -> str:
    if not p:
        return ""
    return os.path.relpath(p, LOCAL_DATA).replace(os.sep, "/")


def build_html() -> str:
    char_ids = _discover_group_char_ids()
    pair_rows: List[str] = []

    if not char_ids:
        body_inner = (
            '<p class="empty">未在 <code>local_data/group/</code> 找到可解析角色 ID 的图片。'
            "请将文件命名为 <code>{角色ID}.png</code> 或 <code>group_{角色ID}.jpg</code> 等形式后重试。</p>"
        )
    else:
        for i in range(0, len(char_ids), 2):
            chunk = char_ids[i : i + 2]
            cells: List[str] = []
            for cid in chunk:
                gen = _find_generated_image(cid)
                orig = _find_original_image(cid)
                grp = _find_group_image(cid)
                gen_r, orig_r, grp_r = (
                    _rel_to_local_data(gen),
                    _rel_to_local_data(orig),
                    _rel_to_local_data(grp),
                )
                cells.append(
                    f"""<div class="card">
<div class="card-hdr"><span class="id-tag">ID {cid}</span></div>
<div class="triplet">
  <div class="slot">
    <div class="slot-lbl">生成 cos</div>
    <div class="img-wrap">{
                    f'<img src="{escape(gen_r)}" alt="生成" loading="lazy">'
                    if gen_r
                    else '<span class="missing">无生成图</span>'
                }</div>
  </div>
  <div class="slot">
    <div class="slot-lbl">角色原图</div>
    <div class="img-wrap">{
                    f'<img src="{escape(orig_r)}" alt="原图" loading="lazy">'
                    if orig_r
                    else '<span class="missing">无原图</span>'
                }</div>
  </div>
  <div class="slot">
    <div class="slot-lbl">合影</div>
    <div class="img-wrap">{
                    f'<img src="{escape(grp_r)}" alt="合影" loading="lazy">'
                    if grp_r
                    else '<span class="missing">无合影</span>'
                }</div>
  </div>
</div>
</div>"""
                )
            pair_rows.append(f'<div class="row-two">{"".join(cells)}</div>')
        body_inner = "".join(pair_rows)

    stats = (
        f"合影目录角色数 {len(char_ids)}"
        if char_ids
        else "未解析到任何角色"
    )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>生成 cos · 角色 · 合影 对比</title>
<style>
:root {{
  --bg:#0c0c0c; --card:#151520; --bd:#2a2a36; --txt:#ddd; --muted:#777;
  --a1:#7c6cf0; --a2:#e0a030; --a3:#4ecdc4;
}}
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
  background:var(--bg); color:var(--txt);
  padding:12px 14px 28px; max-width:1500px; margin:0 auto;
}}
h1 {{
  font-size:17px; font-weight:600; text-align:center; margin-bottom:6px;
  color:#fff;
}}
.sub {{
  text-align:center; font-size:12px; color:var(--muted); margin-bottom:14px;
}}
.row-two {{
  display:grid;
  grid-template-columns:1fr 1fr;
  gap:10px;
  margin-bottom:10px;
}}
@media (max-width:900px) {{
  .row-two {{ grid-template-columns:1fr; }}
}}
.card {{
  background:var(--card);
  border:1px solid var(--bd);
  border-radius:8px;
  padding:8px 10px 10px;
}}
.card-hdr {{ margin-bottom:6px; }}
.id-tag {{
  font-size:11px; color:var(--muted);
  border:1px solid var(--bd); border-radius:6px; padding:1px 6px;
}}
.triplet {{
  display:grid;
  grid-template-columns:repeat(3, 1fr);
  gap:6px;
  align-items:start;
}}
.slot-lbl {{
  font-size:10px; color:var(--muted);
  text-transform:uppercase;
  letter-spacing:0.04em;
  margin-bottom:4px;
  font-weight:600;
}}
.slot:nth-child(1) .slot-lbl {{ color:var(--a2); }}
.slot:nth-child(2) .slot-lbl {{ color:var(--a1); }}
.slot:nth-child(3) .slot-lbl {{ color:var(--a3); }}
.img-wrap {{
  background:#0a0a0f;
  border:1px solid #222;
  border-radius:6px;
  min-height:120px;
  display:flex;
  align-items:center;
  justify-content:center;
  padding:4px;
}}
.img-wrap img {{
  max-width:100%;
  max-height:220px;
  width:auto;
  height:auto;
  object-fit:contain;
  vertical-align:middle;
  display:block;
}}
.missing {{
  font-size:11px; color:#444;
  padding:24px 6px; text-align:center;
}}
.empty {{
  text-align:center; color:var(--muted); font-size:13px; padding:36px 12px;
}}
.empty code {{ color:var(--a1); }}
</style>
</head>
<body>
<h1>生成 cos · 角色原图 · 合影</h1>
<p class="sub">{escape(stats)} · 每行两组 · 等比缩放不裁切</p>
{body_inner}
</body>
</html>
"""


def main() -> None:
    parser = argparse.ArgumentParser(description="生成 cos / 角色 / 合影 紧凑对比页")
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=LOCAL_DATA / "gen_char_group_compare.html",
        help="输出 HTML 路径",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="生成后尝试用 open(1) 打开（macOS）",
    )
    args = parser.parse_args()
    out: Path = args.output
    if not out.is_absolute():
        out = PROJECT_ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_html(), encoding="utf-8")
    print(f"已写入: {out}", file=sys.stderr)
    if args.open and sys.platform == "darwin":
        subprocess.run(["open", str(out)], check=False)


if __name__ == "__main__":
    main()
