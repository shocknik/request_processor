"""Генерирует assets/app_icon.ico — multi-size ICO для ярлыка Lab_request.

Источники (по приоритету):
1) assets/app_logo.png  (рекомендуется класть логотип в assets для релиза)
2) data/logo_cable_test_new_4.jpg  (локальный логотип лаборатории)
3) программный fallback (документ + кабель), если логотипа нет

Запуск: python tools/make_app_icon.py
"""

from __future__ import annotations

import io
import struct
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "app_icon.ico"
LOGO_CANDIDATES = (
    ROOT / "assets" / "app_logo.png",
    ROOT / "assets" / "app_logo.jpg",
    ROOT / "data" / "logo_cable_test_new_4.jpg",
)

# Светлый «матовый» фон в духе GUI (Liquid Glass)
BG_TOP = (245, 247, 252, 255)
BG_BOT = (230, 236, 248, 255)
RING = (0, 122, 255, 255)  # accent iOS blue
SHADOW = (0, 40, 80, 45)

# Размеры ярлыка Windows (Explorer / taskbar / alt-tab)
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def _find_logo() -> Path | None:
    for p in LOGO_CANDIDATES:
        if p.is_file():
            return p
    return None


def _load_logo_rgba() -> Image.Image | None:
    path = _find_logo()
    if path is None:
        return None
    im = Image.open(path).convert("RGBA")
    # Убрать почти-белый фон (jpg логотипа) → прозрачность
    px = im.load()
    w, h = im.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if r > 245 and g > 245 and b > 245:
                px[x, y] = (r, g, b, 0)
            elif r > 230 and g > 230 and b > 230:
                # мягкий край
                fade = int(255 * (255 - min(r, g, b)) / 25)
                px[x, y] = (r, g, b, max(0, min(255, fade)))
    return im


def _rounded_gradient(s: int) -> Image.Image:
    """Скруглённый квадрат с вертикальным градиентом + лёгкая обводка."""
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    margin = max(1, s // 18)
    radius = max(4, s // 5)

    # Тень
    shadow = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    off = max(1, s // 40)
    sd.rounded_rectangle(
        (margin + off, margin + off, s - margin - 1 + off, s - margin - 1 + off),
        radius=radius,
        fill=SHADOW,
    )
    if s >= 32:
        shadow = shadow.filter(ImageFilter.GaussianBlur(radius=max(1, s // 28)))
    img = Image.alpha_composite(img, shadow)

    # Градиент-заливка
    grad = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    gdraw = ImageDraw.Draw(grad)
    for y in range(s):
        t = y / max(1, s - 1)
        col = tuple(int(BG_TOP[i] * (1 - t) + BG_BOT[i] * t) for i in range(3)) + (255,)
        gdraw.line([(0, y), (s, y)], fill=col)
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (margin, margin, s - margin - 1, s - margin - 1),
        radius=radius,
        fill=255,
    )
    plate = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    plate.paste(grad, mask=mask)
    img = Image.alpha_composite(img, plate)

    # Тонкое кольцо accent
    draw = ImageDraw.Draw(img)
    ring_w = max(1, s // 32)
    draw.rounded_rectangle(
        (margin, margin, s - margin - 1, s - margin - 1),
        radius=radius,
        outline=RING,
        width=ring_w,
    )
    # Верхний блик
    if s >= 32:
        hi = Image.new("RGBA", (s, s), (0, 0, 0, 0))
        hd = ImageDraw.Draw(hi)
        hd.rounded_rectangle(
            (margin + 1, margin + 1, s - margin - 2, s // 2),
            radius=radius,
            fill=(255, 255, 255, 50),
        )
        img = Image.alpha_composite(img, hi)
    return img


def _compose_with_logo(s: int, logo: Image.Image) -> Image.Image:
    base = _rounded_gradient(s)
    # Логотип занимает ~72% внутренней области
    pad = max(3, s // 7)
    box = s - 2 * pad
    logo_fit = logo.copy()
    logo_fit.thumbnail((box, box), Image.Resampling.LANCZOS)
    lx = (s - logo_fit.width) // 2
    ly = (s - logo_fit.height) // 2
    base.alpha_composite(logo_fit, (lx, ly))
    if s >= 64:
        base = base.filter(ImageFilter.SMOOTH)
    return base


def _draw_fallback(s: int) -> Image.Image:
    """Документ + кабель, если логотипа нет."""
    ACCENT = (0, 122, 255, 255)
    WHITE = (255, 255, 255, 255)
    SOFT = (255, 255, 255, 230)
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    margin = max(2, s // 14)
    radius = s // 5
    draw.rounded_rectangle(
        (margin, margin, s - margin - 1, s - margin - 1),
        radius=radius,
        fill=ACCENT,
    )
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
        [(doc_x1 - fold, doc_y0), (doc_x1, doc_y0 + fold), (doc_x1 - fold, doc_y0 + fold)],
        fill=SOFT,
    )
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
    cable = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    cdraw = ImageDraw.Draw(cable)
    stroke = max(2, s // 18)
    cx0, cy0 = int(s * 0.18), int(s * 0.72)
    cx1, cy1 = int(s * 0.82), int(s * 0.92)
    cdraw.arc((cx0, cy0 - s // 8, cx1, cy1 + s // 10), start=200, end=340, fill=WHITE, width=stroke)
    tip_r = max(2, s // 28)
    cdraw.ellipse((cx1 - tip_r * 2, cy1 - tip_r * 3, cx1, cy1 - tip_r), fill=WHITE)
    img = Image.alpha_composite(img, cable)
    if s >= 64:
        img = img.filter(ImageFilter.SMOOTH)
    return img


def _render_size(size: int, logo: Image.Image | None) -> Image.Image:
    if logo is not None:
        if size >= 128:
            return _compose_with_logo(size, logo)
        scale = 4
        hi = _compose_with_logo(size * scale, logo)
        return hi.resize((size, size), Image.Resampling.LANCZOS)
    if size >= 128:
        return _draw_fallback(size)
    scale = 4
    hi = _draw_fallback(size * scale)
    return hi.resize((size, size), Image.Resampling.LANCZOS)


def _png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def save_png_ico(path: Path, images: list[Image.Image]) -> None:
    """Multi-size ICO с PNG-кадрами (Vista+)."""
    entries: list[tuple[int, int, bytes]] = []
    for im in images:
        if im.mode != "RGBA":
            im = im.convert("RGBA")
        w, h = im.size
        iw = 0 if w >= 256 else w
        ih = 0 if h >= 256 else h
        entries.append((iw, ih, _png_bytes(im)))

    count = len(entries)
    header = struct.pack("<HHH", 0, 1, count)
    offset = 6 + 16 * count
    dir_entries = b""
    blobs = b""
    for iw, ih, data in entries:
        dir_entries += struct.pack(
            "<BBBBHHII",
            iw,
            ih,
            0,
            0,
            1,
            32,
            len(data),
            offset,
        )
        offset += len(data)
        blobs += data

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + dir_entries + blobs)


def main() -> None:
    logo = _load_logo_rgba()
    # Закрепить логотип в assets/ для релиз-zip (data/ не всегда в пакете)
    if logo is not None:
        logo_out = ROOT / "assets" / "app_logo.png"
        # Сохраняем исходник с альфой (до thumbnail)
        src = _find_logo()
        if src and src.suffix.lower() in {".jpg", ".jpeg"}:
            logo.save(logo_out, format="PNG")
        elif src and src.suffix.lower() == ".png" and src != logo_out:
            logo.save(logo_out, format="PNG")
        elif not logo_out.is_file():
            logo.save(logo_out, format="PNG")
        print(f"logo: {src} → assets/app_logo.png")
    else:
        print("logo: not found, using geometric fallback")

    images = [_render_size(s, logo) for s in SIZES]
    save_png_ico(OUT, images)

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
