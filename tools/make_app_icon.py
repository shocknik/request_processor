"""Генерирует assets/app_icon.ico — multi-size PNG-in-ICO (чёткий ярлык Windows)."""

from __future__ import annotations

import io
import struct
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "app_icon.ico"

ACCENT = (0, 122, 255, 255)
ACCENT_DARK = (0, 90, 200, 255)
WHITE = (255, 255, 255, 255)
SOFT_WHITE = (255, 255, 255, 230)

# Размеры ярлыка Windows (Explorer / taskbar / alt-tab)
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def _draw_hires(canvas_size: int) -> Image.Image:
    """Документ + кабель на синем rounded-квадрате (iOS blue)."""
    s = canvas_size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    margin = max(2, s // 14)
    radius = s // 5
    draw.rounded_rectangle(
        (margin, margin, s - margin - 1, s - margin - 1),
        radius=radius,
        fill=ACCENT,
    )

    # Матовый блик сверху
    highlight = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    hdraw = ImageDraw.Draw(highlight)
    hdraw.rounded_rectangle(
        (margin + 1, margin + 1, s - margin - 2, s // 2 + margin),
        radius=radius,
        fill=(255, 255, 255, 38),
    )
    img = Image.alpha_composite(img, highlight)
    draw = ImageDraw.Draw(img)

    # Лист документа
    doc_w = int(s * 0.42)
    doc_h = int(s * 0.52)
    doc_x0 = (s - doc_w) // 2
    doc_y0 = int(s * 0.22)
    doc_x1 = doc_x0 + doc_w
    doc_y1 = doc_y0 + doc_h
    fold = max(3, s // 12)
    draw.rounded_rectangle(
        (doc_x0, doc_y0, doc_x1, doc_y1),
        radius=max(2, s // 28),
        fill=WHITE,
    )
    draw.polygon(
        [
            (doc_x1 - fold, doc_y0),
            (doc_x1, doc_y0 + fold),
            (doc_x1 - fold, doc_y0 + fold),
        ],
        fill=SOFT_WHITE,
    )

    # Строки на листе
    line_left = doc_x0 + max(3, s // 22)
    line_right = doc_x1 - max(3, s // 18)
    line_y = doc_y0 + fold + max(4, s // 18)
    gap = max(3, s // 16)
    for i, frac in enumerate((1.0, 0.85, 0.7)):
        y = line_y + i * gap
        if y + 1 >= doc_y1 - s // 20:
            break
        x1 = int(line_left + (line_right - line_left) * frac)
        draw.rounded_rectangle(
            (line_left, y, x1, y + max(2, s // 40)),
            radius=1,
            fill=ACCENT,
        )

    # Кабель-дуга
    cable = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    cdraw = ImageDraw.Draw(cable)
    stroke = max(2, s // 18)
    cx0, cy0 = int(s * 0.18), int(s * 0.72)
    cx1, cy1 = int(s * 0.82), int(s * 0.92)
    cdraw.arc(
        (cx0, cy0 - s // 8, cx1, cy1 + s // 10),
        start=200,
        end=340,
        fill=WHITE,
        width=stroke,
    )
    tip_r = max(2, s // 28)
    cdraw.ellipse(
        (cx1 - tip_r * 2, cy1 - tip_r * 3, cx1, cy1 - tip_r),
        fill=WHITE,
    )
    img = Image.alpha_composite(img, cable)

    if s >= 64:
        img = img.filter(ImageFilter.SMOOTH)
    return img


def _render_size(size: int) -> Image.Image:
    """Supersample 4× → LANCZOS для мелких размеров (без лесенок)."""
    if size >= 128:
        return _draw_hires(size)
    scale = 4
    hi = _draw_hires(size * scale)
    return hi.resize((size, size), Image.Resampling.LANCZOS)


def _png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def save_png_ico(path: Path, images: list[Image.Image]) -> None:
    """
    Multi-size ICO с PNG-кадрами (Vista+).
    Pillow 12 часто пишет только 16×16 — пишем контейнер сами.
    """
    entries: list[tuple[int, int, bytes]] = []
    for im in images:
        if im.mode != "RGBA":
            im = im.convert("RGBA")
        w, h = im.size
        # ICO header: 0 → 256 px
        iw = 0 if w >= 256 else w
        ih = 0 if h >= 256 else h
        entries.append((iw, ih, _png_bytes(im)))

    # ICONDIR + ICONDIRENTRY*n + data
    count = len(entries)
    header = struct.pack("<HHH", 0, 1, count)  # reserved, type=icon, count
    offset = 6 + 16 * count
    dir_entries = b""
    blobs = b""
    for iw, ih, data in entries:
        dir_entries += struct.pack(
            "<BBBBHHII",
            iw,  # width
            ih,  # height
            0,  # color count
            0,  # reserved
            1,  # planes
            32,  # bit count
            len(data),
            offset,
        )
        offset += len(data)
        blobs += data

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + dir_entries + blobs)


def main() -> None:
    images = [_render_size(s) for s in SIZES]
    save_png_ico(OUT, images)

    # Verify via raw header (Pillow may still open only first frame)
    raw = OUT.read_bytes()
    _reserved, itype, count = struct.unpack_from("<HHH", raw, 0)
    sizes_found: list[str] = []
    for i in range(count):
        entry = struct.unpack_from("<BBBBHHII", raw, 6 + i * 16)
        w, h = entry[0] or 256, entry[1] or 256
        sizes_found.append(f"{w}x{h}")
    print(f"{OUT}")
    print(f"  {OUT.stat().st_size} bytes, {count} sizes: {', '.join(sizes_found)}")


if __name__ == "__main__":
    main()
