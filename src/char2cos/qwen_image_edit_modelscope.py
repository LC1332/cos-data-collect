"""
使用 ModelScope 推理 API 调用 Qwen-Image-Edit（如 Qwen/Qwen-Image-Edit-2511）。

说明：服务端会拉取 image_url，因此须使用公网可访问的图片地址。
配置方式（按优先级）：
  1) 环境变量 MODELSCOPE_SOURCE_IMAGE_URL — 直接指定完整图片 URL
  2) 环境变量 MODELSCOPE_IMAGE_PUBLIC_BASE_URL — 公网目录前缀，脚本用本地文件的 basename 拼接
  3) 未设置上述变量时，尝试将本地图编码为 data:image/...;base64,...（若接口不支持会报错）

Token：环境变量 MODEL_SCOPE_KEY（与仓库 readme 一致），也可使用 MODELSCOPE_API_TOKEN。

用法示例：
  export MODEL_SCOPE_KEY=ms-xxxx
  export MODELSCOPE_IMAGE_PUBLIC_BASE_URL=https://your-domain.com/static/character_images
  python -m src.char2cos.qwen_image_edit_modelscope

  或直接指定公网图：
  export MODELSCOPE_SOURCE_IMAGE_URL=https://example.com/1211_large.jpg
  python -m src.char2cos.qwen_image_edit_modelscope
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import sys
import time
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv
from PIL import Image
from io import BytesIO

API_BASE = "https://api-inference.modelscope.cn/"
DEFAULT_MODEL = "Qwen/Qwen-Image-Edit-2511"
DEFAULT_IMAGE = (
    Path(__file__).resolve().parents[2]
    / "local_data"
    / "bangumi"
    / "character_images"
    / "1211_medium.jpg"
)
DEFAULT_PROMPT = (
    "把图片转化为物语系列的忍野忍的真人cosplay, 年轻, 大学生, photorealistic"
)
POLL_INTERVAL_SEC = 5
POLL_TIMEOUT_SEC = 600
# ModelScope 图像编辑接口对输入边长的常见上限（超出会返回 400）
MAX_INPUT_SIDE = 2048


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve_token() -> str:
    token = (os.environ.get("MODEL_SCOPE_KEY") or os.environ.get("MODELSCOPE_API_TOKEN") or "").strip()
    if not token:
        print(
            "错误：未设置 MODEL_SCOPE_KEY（或 MODELSCOPE_API_TOKEN）。"
            "获取方式：https://www.modelscope.cn/my/myaccesstoken",
            file=sys.stderr,
        )
        sys.exit(1)
    return token


def _guess_mime(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    return mime or "image/jpeg"


def _local_file_to_data_url(path: Path) -> str:
    img = Image.open(path).convert("RGB")
    w, h = img.size
    m = max(w, h)
    if m > MAX_INPUT_SIDE:
        scale = MAX_INPUT_SIDE / m
        img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=95)
    raw = buf.getvalue()
    b64 = base64.standard_b64encode(raw).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


def _build_image_urls(local_path: Path) -> list[str]:
    direct = (os.environ.get("MODELSCOPE_SOURCE_IMAGE_URL") or "").strip()
    if direct:
        return [direct]
    base = (os.environ.get("MODELSCOPE_IMAGE_PUBLIC_BASE_URL") or "").strip().rstrip("/")
    if base:
        return [f"{base}/{local_path.name}"]
    return [_local_file_to_data_url(local_path)]


def _normalize_output_url(output_images: Any) -> str:
    if output_images is None:
        raise ValueError("响应中缺少 output_images")
    if isinstance(output_images, list):
        if not output_images:
            raise ValueError("output_images 为空列表")
        return output_images[0]
    if isinstance(output_images, str):
        return output_images
    raise TypeError(f"无法解析 output_images 类型: {type(output_images)}")


def submit_edit(
    token: str,
    model: str,
    prompt: str,
    image_urls: list[str],
) -> str:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-ModelScope-Async-Mode": "true",
    }
    payload = {
        "model": model,
        "prompt": prompt,
        "image_url": image_urls,
    }
    r = requests.post(
        f"{API_BASE}v1/images/generations",
        headers=headers,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        timeout=120,
    )
    if not r.ok:
        try:
            detail = r.json()
        except Exception:
            detail = r.text
        raise RuntimeError(f"提交任务失败 HTTP {r.status_code}: {detail}")
    body = r.json()
    task_id = body.get("task_id")
    if not task_id:
        raise RuntimeError(f"响应中无 task_id: {body}")
    return task_id


def poll_until_done(token: str, task_id: str) -> str:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "X-ModelScope-Task-Type": "image_generation",
    }
    start = time.time()
    while True:
        if time.time() - start > POLL_TIMEOUT_SEC:
            raise TimeoutError(f"轮询超时（{POLL_TIMEOUT_SEC}s）")
        r = requests.get(
            f"{API_BASE}v1/tasks/{task_id}",
            headers=headers,
            timeout=60,
        )
        r.raise_for_status()
        data = r.json()
        status = data.get("task_status")
        print(f"  任务状态: {status}")
        if status == "SUCCEED":
            return _normalize_output_url(data.get("output_images"))
        if status == "FAILED":
            err = data.get("error", data.get("message", "未知错误"))
            raise RuntimeError(f"任务失败: {err}")
        time.sleep(POLL_INTERVAL_SEC)


def _pil_to_rgb(im: Image.Image) -> Image.Image:
    """API 常返回带 alpha 的 PNG；直接 convert('RGB') 会把透明像素变成黑色。"""
    if im.mode == "RGBA":
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[3])
        return bg
    if im.mode == "LA":
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[3])
        return bg
    if im.mode == "P" and "transparency" in im.info:
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.split()[3])
        return bg
    return im.convert("RGB")


def download_image(url: str) -> Image.Image:
    resp = requests.get(url, timeout=120)
    resp.raise_for_status()
    return _pil_to_rgb(Image.open(BytesIO(resp.content)))


def main() -> None:
    load_dotenv(_repo_root() / ".env")

    parser = argparse.ArgumentParser(description="ModelScope Qwen-Image-Edit 调用示例")
    parser.add_argument("--image", type=Path, default=DEFAULT_IMAGE, help="本地输入图片路径")
    parser.add_argument("--prompt", type=str, default=DEFAULT_PROMPT, help="编辑指令")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL, help="ModelScope 模型 ID")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="输出路径（默认 local_data/char2cos/qwen_edit_<stem>.jpg）",
    )
    args = parser.parse_args()

    local_path: Path = args.image.expanduser().resolve()
    if not local_path.is_file():
        print(f"错误：本地图片不存在: {local_path}", file=sys.stderr)
        sys.exit(1)

    token = _resolve_token()
    image_urls = _build_image_urls(local_path)

    print(f"模型: {args.model}")
    print(f"提示词: {args.prompt}")
    if image_urls[0].startswith("data:"):
        print("图片来源: data URL（base64，若接口拒绝请设置 MODELSCOPE_SOURCE_IMAGE_URL 或 MODELSCOPE_IMAGE_PUBLIC_BASE_URL）")
    else:
        print(f"图片来源 URL: {image_urls[0]}")

    print("提交异步任务…")
    task_id = submit_edit(token, args.model, args.prompt, image_urls)
    print(f"task_id: {task_id}")

    print("轮询结果…")
    out_url = poll_until_done(token, task_id)
    print(f"结果 URL: {out_url}")

    img = download_image(out_url)
    out_path = args.out
    if out_path is None:
        out_dir = _repo_root() / "local_data" / "char2cos"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"qwen_edit_{local_path.stem}.jpg"
    else:
        out_path = out_path.expanduser().resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)

    img.save(out_path, format="JPEG", quality=95)
    print(f"已保存: {out_path}")


if __name__ == "__main__":
    main()
