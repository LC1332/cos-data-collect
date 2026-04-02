"""将角色原图和 cosplay 搜索结果拼成 2 行 3 列的标注图。

布局:
  Original_Character | pic_A | pic_B
  pic_C              | pic_D | pic_E

所有图片等比例缩放（不裁剪），居中放置在对应单元格中。
"""

from pathlib import Path
from typing import List, Optional, Union

from PIL import Image, ImageDraw, ImageFont

CELL_W = 400
CELL_H = 500
LABEL_H = 32
COLS, ROWS = 3, 2
LABELS = ["Original_Character", "pic_A", "pic_B", "pic_C", "pic_D", "pic_E"]

_FONT_PATHS = [
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/Arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
]


def _load_font(size: int = 18) -> ImageFont.FreeTypeFont:
    for fp in _FONT_PATHS:
        try:
            return ImageFont.truetype(fp, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _resize_keep_aspect(img: Image.Image, max_w: int, max_h: int) -> Image.Image:
    ratio = min(max_w / img.width, max_h / img.height)
    new_w = int(img.width * ratio)
    new_h = int(img.height * ratio)
    return img.resize((new_w, new_h), Image.LANCZOS)


def compose_grid(
    original_path: Union[str, Path, None],
    cosplay_paths: List[Union[str, Path]],
    output_path: Union[str, Path],
    cell_w: int = CELL_W,
    cell_h: int = CELL_H,
    label_h: int = LABEL_H,
) -> Path:
    """创建 2×3 标注网格图。

    Args:
        original_path: 角色原图路径（左上角）
        cosplay_paths: 至多 5 张 cosplay 搜索结果路径
        output_path: 输出图片路径
    Returns:
        output_path
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    canvas_w = COLS * cell_w
    canvas_h = ROWS * (cell_h + label_h)
    canvas = Image.new("RGB", (canvas_w, canvas_h), (30, 30, 30))
    draw = ImageDraw.Draw(canvas)
    font = _load_font(18)

    all_paths: list = [original_path] + list(cosplay_paths)[:5]
    # 补齐到 6 格
    while len(all_paths) < 6:
        all_paths.append(None)

    for idx in range(6):
        row, col = divmod(idx, COLS)
        x = col * cell_w
        y = row * (cell_h + label_h)

        label = LABELS[idx]
        bbox = draw.textbbox((0, 0), label, font=font)
        text_w = bbox[2] - bbox[0]
        label_color = (180, 130, 255) if idx == 0 else (255, 255, 255)
        draw.text(
            (x + (cell_w - text_w) // 2, y + (label_h - (bbox[3] - bbox[1])) // 2),
            label,
            fill=label_color,
            font=font,
        )

        img_y = y + label_h
        p = all_paths[idx]
        if p and Path(p).exists():
            try:
                img = Image.open(p).convert("RGB")
                img = _resize_keep_aspect(img, cell_w - 8, cell_h - 8)
                paste_x = x + (cell_w - img.width) // 2
                paste_y = img_y + (cell_h - img.height) // 2
                canvas.paste(img, (paste_x, paste_y))
            except Exception:
                _draw_placeholder(draw, x, img_y, cell_w, cell_h, "Load Error", font)
        else:
            _draw_placeholder(draw, x, img_y, cell_w, cell_h, "No Image", font)

    canvas.save(str(output_path), "JPEG", quality=85)
    return output_path


def _draw_placeholder(
    draw: ImageDraw.ImageDraw,
    x: int, y: int,
    w: int, h: int,
    text: str,
    font: ImageFont.FreeTypeFont,
):
    draw.rectangle([x + 4, y + 4, x + w - 4, y + h - 4], outline=(60, 60, 60))
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(
        (x + (w - tw) // 2, y + (h - th) // 2),
        text,
        fill=(80, 80, 80),
        font=font,
    )
