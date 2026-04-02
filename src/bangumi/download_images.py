"""角色图片下载器。

从 characters_ranked.json 中读取角色列表，按 large > medium > grid > small 优先级
为每个角色下载最多 2 张有效图片。支持断点续传和失败重试。
"""

import json
import logging
import os
import random
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

DATA_DIR = PROJECT_ROOT / "local_data" / "bangumi"
IMAGE_DIR = DATA_DIR / "character_images"
PROGRESS_FILE = DATA_DIR / "image_download_progress.json"

IMAGE_PRIORITY = ["large", "medium", "grid", "small"]
MAX_IMAGES_PER_CHAR = 2
MAX_RETRIES = 5
RETRY_BACKOFF_BASE = 2

# 8416 chars × 2 images ≈ 16832 downloads
# 6s per download → ~28h ≈ 1.2 days
BASE_DELAY = 6.0
JITTER = 2.0

REQUEST_TIMEOUT = 30

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "cos-data-collect/0.1 (https://github.com/cos-data-collect)",
    "Accept": "image/*,*/*",
    "Referer": "https://bgm.tv/",
})


def load_characters(path: Path) -> List[dict]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_progress() -> Dict[int, List[str]]:
    """加载已下载的进度，格式: {char_id: [saved_filename, ...]}"""
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        return {int(k): v for k, v in raw.items()}
    return {}


def save_progress(progress: Dict[int, List[str]]):
    with open(PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump(progress, f, ensure_ascii=False, indent=2)


def download_one_image(url: str, save_path: Path) -> bool:
    """下载单张图片，支持最多 MAX_RETRIES 次重试。"""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = SESSION.get(url, timeout=REQUEST_TIMEOUT, stream=True)
            if resp.status_code == 200:
                content_type = resp.headers.get("Content-Type", "")
                if "image" not in content_type and len(resp.content) < 500:
                    logger.warning(f"  非图片内容 (Content-Type: {content_type}), 跳过")
                    return False
                save_path.parent.mkdir(parents=True, exist_ok=True)
                with open(save_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        f.write(chunk)
                return True
            elif resp.status_code == 404:
                logger.warning(f"  404 Not Found, 跳过: {url}")
                return False
            else:
                logger.warning(f"  HTTP {resp.status_code}, 重试 {attempt}/{MAX_RETRIES}")
        except requests.RequestException as e:
            logger.warning(f"  请求异常: {e}, 重试 {attempt}/{MAX_RETRIES}")

        if attempt < MAX_RETRIES:
            wait = RETRY_BACKOFF_BASE ** attempt + random.uniform(0, 1)
            time.sleep(wait)

    return False


def get_image_extension(url: str) -> str:
    path_part = url.split("?")[0]
    if "." in path_part:
        ext = path_part.rsplit(".", 1)[-1].lower()
        if ext in ("jpg", "jpeg", "png", "gif", "webp"):
            return ext
    return "jpg"


def download_character_images(
    characters: List[dict],
    limit: Optional[int] = None,
    base_delay: float = BASE_DELAY,
    jitter: float = JITTER,
) -> Dict[int, List[str]]:
    """为角色列表下载图片。

    Args:
        characters: 角色列表（已按 collects 降序排列）
        limit: 只处理前 N 个角色（None=全部）
        base_delay: 每次下载后的基础延迟秒数
        jitter: 延迟的随机抖动范围
    """
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    progress = load_progress()

    if limit:
        characters = characters[:limit]

    total = len(characters)
    already_done = sum(1 for ch in characters if ch["id"] in progress)
    logger.info(f"角色总数: {total}, 已完成: {already_done}, 待处理: {total - already_done}")

    for idx, ch in enumerate(characters):
        cid = ch["id"]
        name = ch.get("name_cn") or ch.get("name", f"char_{cid}")

        if cid in progress:
            continue

        images = ch.get("images") or {}
        if not images:
            logger.info(f"  [{idx+1}/{total}] {name} (id={cid}) - 无图片数据, 跳过")
            progress[cid] = []
            continue

        logger.info(f"  [{idx+1}/{total}] {name} (id={cid})")

        saved_files = []
        for size_key in IMAGE_PRIORITY:
            if len(saved_files) >= MAX_IMAGES_PER_CHAR:
                break
            url = images.get(size_key)
            if not url:
                continue

            ext = get_image_extension(url)
            filename = f"{cid}_{size_key}.{ext}"
            save_path = IMAGE_DIR / filename

            if save_path.exists():
                saved_files.append(filename)
                logger.info(f"    {size_key}: 已存在 {filename}")
                continue

            delay = base_delay + random.uniform(-jitter, jitter)
            time.sleep(max(delay, 1.0))

            ok = download_one_image(url, save_path)
            if ok:
                saved_files.append(filename)
                logger.info(f"    {size_key}: 已下载 {filename}")
            else:
                logger.warning(f"    {size_key}: 下载失败")

        progress[cid] = saved_files

        if (idx + 1) % 50 == 0:
            save_progress(progress)
            done = sum(1 for ch2 in characters if ch2["id"] in progress)
            logger.info(f"  === 进度保存: {done}/{total} ===")

    save_progress(progress)
    done_count = sum(1 for v in progress.values() if v)
    empty_count = sum(1 for v in progress.values() if not v)
    logger.info(f"下载完成! 成功: {done_count}, 无图片/失败: {empty_count}")
    return progress


def generate_gallery_html(characters: List[dict], progress: Dict[int, List[str]], limit: Optional[int] = None):
    """生成角色图片展示 HTML 页面（每个角色展示 1 张图片）。"""
    if limit:
        characters = characters[:limit]

    html_path = DATA_DIR / "character_gallery.html"

    rows = []
    for ch in characters:
        cid = ch["id"]
        files = progress.get(cid, [])
        if not files:
            continue
        img_file = files[0]
        name = ch.get("name_cn") or ch.get("name", f"char_{cid}")
        jp_name = ch.get("name", "")
        collects = ch.get("collects", 0)
        rows.append({
            "img": f"character_images/{img_file}",
            "name": name,
            "jp_name": jp_name,
            "collects": collects,
            "cid": cid,
        })

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Bangumi 角色图片一览 ({len(rows)} 角色)</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: #1a1a2e; color: #eee; padding: 24px;
  }}
  h1 {{
    text-align: center; margin-bottom: 8px; font-size: 1.6rem;
    background: linear-gradient(135deg, #667eea, #764ba2);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
  }}
  .subtitle {{ text-align: center; color: #888; margin-bottom: 24px; font-size: 0.9rem; }}
  .grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
    gap: 16px; max-width: 1400px; margin: 0 auto;
  }}
  .card {{
    background: #16213e; border-radius: 12px; overflow: hidden;
    transition: transform 0.2s, box-shadow 0.2s;
    box-shadow: 0 2px 8px rgba(0,0,0,0.3);
  }}
  .card:hover {{ transform: translateY(-4px); box-shadow: 0 8px 24px rgba(102,126,234,0.3); }}
  .card img {{
    width: 100%; aspect-ratio: 3/4; object-fit: cover; object-position: top;
    background: #0f3460;
  }}
  .card .info {{ padding: 10px 12px; }}
  .card .name {{ font-weight: 600; font-size: 0.95rem; margin-bottom: 2px;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  .card .jp {{ font-size: 0.78rem; color: #999; margin-bottom: 4px;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  .card .stat {{ font-size: 0.75rem; color: #667eea; }}
</style>
</head>
<body>
<h1>Bangumi 角色图片一览</h1>
<p class="subtitle">共 {len(rows)} 位角色 · 按收藏数排序</p>
<div class="grid">
"""
    for r in rows:
        html += f"""  <div class="card">
    <img src="{r['img']}" alt="{r['name']}" loading="lazy">
    <div class="info">
      <div class="name" title="{r['name']}">{r['name']}</div>
      <div class="jp" title="{r['jp_name']}">{r['jp_name']}</div>
      <div class="stat">♥ {r['collects']} 收藏 · ID {r['cid']}</div>
    </div>
  </div>
"""
    html += """</div>
</body>
</html>
"""
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    logger.info(f"Gallery HTML 已生成: {html_path} ({len(rows)} 个角色)")
    return html_path


def main():
    import argparse

    parser = argparse.ArgumentParser(description="下载 Bangumi 角色图片")
    parser.add_argument("--limit", type=int, default=None,
                        help="只下载前 N 个角色 (默认全部)")
    parser.add_argument("--delay", type=float, default=BASE_DELAY,
                        help=f"每次下载的基础延迟秒数 (默认 {BASE_DELAY})")
    parser.add_argument("--jitter", type=float, default=JITTER,
                        help=f"延迟随机抖动范围 (默认 {JITTER})")
    parser.add_argument("--gallery-only", action="store_true",
                        help="只生成 Gallery HTML，不下载图片")
    parser.add_argument("--input", type=str, default=None,
                        help="输入角色 JSON 文件路径 (默认 characters_ranked.json)")
    args = parser.parse_args()

    input_path = Path(args.input) if args.input else DATA_DIR / "characters_ranked.json"
    if not input_path.exists():
        logger.error(f"角色数据文件不存在: {input_path}")
        logger.error("请先运行 src/bangumi/main.py 采集角色数据")
        sys.exit(1)

    characters = load_characters(input_path)
    logger.info(f"已加载 {len(characters)} 个角色")

    if args.gallery_only:
        progress = load_progress()
        generate_gallery_html(characters, progress, limit=args.limit)
        return

    logger.info("=" * 60)
    logger.info("角色图片下载开始")
    logger.info(f"  角色数: {args.limit or len(characters)}")
    logger.info(f"  延迟: {args.delay}s ± {args.jitter}s")
    logger.info(f"  每角色最多: {MAX_IMAGES_PER_CHAR} 张")
    logger.info(f"  优先级: {' > '.join(IMAGE_PRIORITY)}")
    logger.info(f"  重试次数: {MAX_RETRIES}")
    logger.info("=" * 60)

    progress = download_character_images(
        characters,
        limit=args.limit,
        base_delay=args.delay,
        jitter=args.jitter,
    )

    generate_gallery_html(characters, progress, limit=args.limit)

    logger.info("全部完成!")


if __name__ == "__main__":
    main()
