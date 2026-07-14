"""
Table OCR v1: detect grid / row strips on scanned pages, OCR per cell.

Improvements over v0 (35s):
- Auto-orient via Tesseract OSD before grid detection (FLEXICORE p.2 was 90°).
- Default 400 DPI for PDF render.
- CLAHE contrast + multi-PSM cell OCR.
- Wider mark-column heuristics when vertical lines are dense (text stems).

Strategies:
1. Full grid — OpenCV H/V lines → per-cell Tesseract.
2. Row-strip fallback — mark column band-by-band via ink projection.

See Obsidian 35b §4.3, 35s — Table OCR v1.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .preprocess import (
    correct_orientation,
    enhance_contrast,
    is_cv_available,
    preprocess_for_ocr,
)

if TYPE_CHECKING:
    from PIL import Image

logger = logging.getLogger(__name__)

TABLE_OCR_VERSION = "v1"
TABLE_OCR_DPI = 400
MIN_TABLE_ROWS = 3
MIN_TABLE_COLS = 2
MIN_LINE_SPAN_RATIO = 0.35
H_LINE_FALLBACK_RATIOS = (0.35, 0.2, 0.12, 0.08)
CELL_PADDING_PX = 4
MARK_COLUMN_INDEX = 1
ROW_STRIP_MIN_HEIGHT = 14
ROW_STRIP_MAX_HEIGHT = 120
ROW_MERGE_GAP_PX = 18
# Prefer eng for Latin brand tables (FLEXICORE); rus+eng as fallback.
CELL_LANGS = ("eng", "rus+eng")
CELL_PSMS = (7, 6, 4)


@dataclass
class TableOcrResult:
    """Structured output of table OCR on one page."""

    page_index: int
    rows: list[list[str]] = field(default_factory=list)
    text: str = ""
    cell_count: int = 0
    grid_rows: int = 0
    grid_cols: int = 0
    version: str = TABLE_OCR_VERSION
    mode: str = "grid"
    oriented: bool = False


def _pil_to_gray(image: Image.Image) -> Any:
    import cv2
    import numpy as np

    arr = np.array(image.convert("RGB"))
    return cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)


def _detect_line_positions(
    gray: Any,
    *,
    direction: str,
    min_span_ratio: float = MIN_LINE_SPAN_RATIO,
) -> list[int]:
    """Return sorted pixel positions of horizontal or vertical grid lines."""
    import cv2
    import numpy as np

    h, w = gray.shape[:2]
    if direction == "horizontal":
        kernel_len = max(w // 30, 40)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (kernel_len, 1))
        span = w
    else:
        kernel_len = max(h // 30, 40)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, kernel_len))
        span = h

    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel, iterations=1)
    lines = cv2.dilate(lines, kernel, iterations=1)

    if direction == "horizontal":
        projection = np.sum(lines, axis=1)
        axis_len = h
    else:
        projection = np.sum(lines, axis=0)
        axis_len = w

    threshold = span * 255 * min_span_ratio
    positions: list[int] = []
    in_run = False
    run_start = 0
    for idx, value in enumerate(projection):
        if value >= threshold:
            if not in_run:
                in_run = True
                run_start = idx
        elif in_run:
            positions.append((run_start + idx) // 2)
            in_run = False
    if in_run:
        positions.append((run_start + axis_len - 1) // 2)

    merged: list[int] = []
    min_gap = max(8, axis_len // 80)
    for pos in positions:
        if merged and pos - merged[-1] < min_gap:
            merged[-1] = (merged[-1] + pos) // 2
        else:
            merged.append(pos)

    if direction == "horizontal":
        merged = [p for p in merged if 0 < p < h - 1]
    else:
        merged = [p for p in merged if 0 < p < w - 1]
    return merged


def _detect_horizontal_lines_adaptive(gray: Any) -> list[int]:
    for ratio in H_LINE_FALLBACK_RATIOS:
        lines = _detect_line_positions(gray, direction="horizontal", min_span_ratio=ratio)
        if len(lines) >= MIN_TABLE_ROWS - 1:
            return lines
    return _detect_line_positions(gray, direction="horizontal", min_span_ratio=H_LINE_FALLBACK_RATIOS[-1])


def _major_vertical_edges(v_lines: list[int], *, width: int) -> list[int]:
    """Collapse dense vertical lines into major column boundaries."""
    if not v_lines:
        return [0, width]
    edges = [0]
    gap_threshold = max(60, width // 25)
    for line in v_lines:
        if line - edges[-1] >= gap_threshold:
            edges.append(line)
    if width - edges[-1] >= gap_threshold // 2:
        edges.append(width)
    return edges


def _infer_mark_column_bounds(v_lines: list[int], *, width: int) -> tuple[int, int]:
    """
    Guess the mark-name column (2nd column in FLEXICORE-style application tables).

    When vertical detection is noisy (letter stems), fall back to form ratios:
    № ≈ 0–8%, mark name ≈ 8–42%, TU ≈ 42–62%.
    """
    edges = _major_vertical_edges(v_lines, width=width)
    if len(edges) >= 4:
        # Prefer a reasonably wide 2nd column (mark names need ~25%+ width)
        for i in range(1, len(edges) - 1):
            x0, x1 = edges[i], edges[i + 1]
            col_w = x1 - x0
            if col_w >= width * 0.18 and x0 <= width * 0.25:
                return x0, x1
        return edges[1], edges[2]
    if len(edges) == 3:
        x0, x1 = edges[1], edges[2]
        if x1 - x0 >= width * 0.15:
            return x0, x1
    # Ratio fallback for Word-export scans without clean verticals
    return int(width * 0.08), int(width * 0.45)


def _detect_text_row_bands(gray_roi: Any) -> list[tuple[int, int]]:
    """Find text row bands inside a column ROI via ink projection."""
    import cv2
    import numpy as np

    _, binary = cv2.threshold(gray_roi, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    projection = np.sum(binary, axis=1)
    if projection.size == 0 or projection.max() == 0:
        return []

    threshold = projection.max() * 0.06
    bands: list[tuple[int, int]] = []
    in_run = False
    run_start = 0
    for idx, value in enumerate(projection):
        if value >= threshold:
            if not in_run:
                in_run = True
                run_start = idx
        elif in_run:
            bands.append((run_start, idx))
            in_run = False
    if in_run:
        bands.append((run_start, len(projection)))

    merged: list[tuple[int, int]] = []
    for band in bands:
        if merged and band[0] - merged[-1][1] < ROW_MERGE_GAP_PX:
            merged[-1] = (merged[-1][0], band[1])
        else:
            merged.append(band)
    return [
        band
        for band in merged
        if ROW_STRIP_MIN_HEIGHT <= band[1] - band[0] <= ROW_STRIP_MAX_HEIGHT
    ]


CellBox = tuple[int, int, int, int, int, int]


def _build_cell_boxes(
    h_lines: list[int],
    v_lines: list[int],
    *,
    height: int,
    width: int,
) -> list[CellBox]:
    h_edges = [0] + h_lines + [height]
    v_edges = [0] + v_lines + [width]
    boxes: list[CellBox] = []
    for row in range(len(h_edges) - 1):
        y0, y1 = h_edges[row], h_edges[row + 1]
        if y1 - y0 < 12:
            continue
        for col in range(len(v_edges) - 1):
            x0, x1 = v_edges[col], v_edges[col + 1]
            if x1 - x0 < 20:
                continue
            boxes.append((x0, y0, x1, y1, row, col))
    return boxes


def _crop_cell(gray: Any, box: CellBox) -> Any:
    x0, y0, x1, y1, _row, _col = box
    pad = CELL_PADDING_PX
    h, w = gray.shape[:2]
    x0 = max(0, x0 + pad)
    y0 = max(0, y0 + pad)
    x1 = min(w, x1 - pad)
    y1 = min(h, y1 - pad)
    if x1 <= x0 or y1 <= y0:
        return None
    return gray[y0:y1, x0:x1]


def _score_ocr_text(text: str) -> float:
    """Prefer Latin brand tokens and alnum over punctuation garbage."""
    if not text:
        return -1.0
    cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) < 2:
        return -1.0
    alnum = sum(ch.isalnum() for ch in cleaned)
    ratio = alnum / max(len(cleaned), 1)
    score = len(cleaned) * ratio
    upper = cleaned.upper()
    for token in ("FLEXICORE", "H07RN", "LIYCY", "LIYY", "FLAT", "VICAB"):
        if token in upper:
            score += 50
    if re.search(r"\d", cleaned):
        score += 5
    return score


def _ocr_cell_image(cell_gray: Any, pytesseract: Any, *, psm: int = 7) -> str:
    from PIL import Image

    pil = Image.fromarray(cell_gray)
    pil = enhance_contrast(pil)
    # Cells are already cropped — skip upscale to avoid multi-megapixel images.
    pil = preprocess_for_ocr(
        pil,
        upscale=False,
        adaptive_threshold=True,
        contrast=False,
        denoise=True,
    )
    best = ""
    best_score = -1.0
    for lang in CELL_LANGS:
        config = f"--psm {psm} --oem 1"
        try:
            text = pytesseract.image_to_string(pil, lang=lang, config=config)
        except Exception:
            continue
        text = re.sub(r"\s+", " ", text).strip()
        score = _score_ocr_text(text)
        if score > best_score:
            best_score = score
            best = text
    return best


def _ocr_cell_best(cell_gray: Any, pytesseract: Any) -> str:
    best = ""
    best_score = -1.0
    for psm in CELL_PSMS:
        text = _ocr_cell_image(cell_gray, pytesseract, psm=psm)
        score = _score_ocr_text(text)
        if score > best_score:
            best_score = score
            best = text
    return best


def _find_tesseract(pytesseract: Any) -> str | None:
    from ..pdf_extractor import _find_tesseract

    cmd = _find_tesseract()
    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd
    return cmd


def _ocr_grid_cells(
    gray: Any,
    h_lines: list[int],
    v_lines: list[int],
    pytesseract: Any,
    *,
    page_index: int,
    mark_column_only: bool,
    oriented: bool,
) -> TableOcrResult | None:
    h, w = gray.shape[:2]
    raw_boxes = _build_cell_boxes(h_lines, v_lines, height=h, width=w)
    if not raw_boxes:
        return None

    max_row = max(b[4] for b in raw_boxes)
    max_col = max(b[5] for b in raw_boxes)
    if max_row + 1 < MIN_TABLE_ROWS or max_col + 1 < MIN_TABLE_COLS:
        return None

    grid: list[list[str]] = [
        ["" for _ in range(max_col + 1)] for _ in range(max_row + 1)
    ]
    cell_count = 0
    for box in raw_boxes:
        _x0, _y0, _x1, _y1, row, col = box
        if mark_column_only and col != MARK_COLUMN_INDEX:
            continue
        cell_img = _crop_cell(gray, box)
        if cell_img is None:
            continue
        text = _ocr_cell_best(cell_img, pytesseract)
        if text:
            grid[row][col] = text
            cell_count += 1

    non_empty_rows = [row for row in grid if any(cell.strip() for cell in row)]
    if len(non_empty_rows) < MIN_TABLE_ROWS:
        return None

    lines = [" | ".join(c.strip() for c in row if c.strip()) for row in non_empty_rows]
    return TableOcrResult(
        page_index=page_index,
        rows=non_empty_rows,
        text="\n".join(lines),
        cell_count=cell_count,
        grid_rows=len(non_empty_rows),
        grid_cols=max_col + 1,
        mode="grid",
        oriented=oriented,
    )


def _is_plausible_table_text(text: str) -> bool:
    """Reject garbage grid OCR (punctuation-only cells)."""
    cleaned = re.sub(r"[^\wА-Яа-яЁё]+", " ", text, flags=re.UNICODE)
    words = [w for w in cleaned.split() if len(w) >= 3]
    upper = text.upper()
    brand_hit = any(t in upper for t in ("FLEXICORE", "H07RN", "VICAB", "СПЕЦЛАН", "КГ"))
    return (len(text.strip()) >= 30 and len(words) >= 2) or brand_hit


def _ocr_row_strips(
    gray: Any,
    pytesseract: Any,
    *,
    page_index: int,
    v_lines: list[int],
    oriented: bool,
) -> TableOcrResult | None:
    """Fallback: OCR mark column row-by-row when horizontal grid lines are weak."""
    h, w = gray.shape[:2]
    x0, x1 = _infer_mark_column_bounds(v_lines, width=w)
    y0 = int(h * 0.08)
    y1 = int(h * 0.95)
    roi = gray[y0:y1, x0:x1]
    bands = _detect_text_row_bands(roi)
    if len(bands) < MIN_TABLE_ROWS:
        return None

    rows: list[list[str]] = []
    cell_count = 0
    for band_y0, band_y1 in bands:
        # small vertical pad so descenders are not cut
        pad = 2
        sy0 = max(0, band_y0 - pad)
        sy1 = min(roi.shape[0], band_y1 + pad)
        strip = roi[sy0:sy1]
        text = _ocr_cell_best(strip, pytesseract)
        if not text or len(text) < 3:
            continue
        rows.append([text])
        cell_count += 1

    if len(rows) < MIN_TABLE_ROWS:
        return None

    lines = [row[0] for row in rows]
    return TableOcrResult(
        page_index=page_index,
        rows=rows,
        text="\n".join(lines),
        cell_count=cell_count,
        grid_rows=len(rows),
        grid_cols=1,
        mode="row_strip",
        oriented=oriented,
    )


def _prepare_page_image(
    image: Image.Image,
    *,
    auto_orient: bool,
    tesseract_cmd: str | None,
) -> tuple[Image.Image, bool]:
    if not auto_orient:
        return image, False
    oriented_img = correct_orientation(image, tesseract_cmd=tesseract_cmd)
    changed = oriented_img.size != image.size or oriented_img is not image
    # size change is reliable signal for 90/270; for 180 compare id
    if oriented_img is not image:
        return oriented_img, True
    return image, False


def ocr_table_from_image(
    image: Image.Image,
    *,
    page_index: int = 0,
    mark_column_only: bool = True,
    auto_orient: bool = True,
) -> TableOcrResult | None:
    """
    Detect table structure on a page image and OCR mark cells.

    Tries full grid first; falls back to row-strip OCR in the mark column.
    """
    if not is_cv_available():
        logger.debug("Table OCR skipped — OpenCV not installed")
        return None

    import pytesseract

    cmd = _find_tesseract(pytesseract)
    if not cmd:
        logger.warning("Table OCR skipped — Tesseract not found")
        return None

    working, oriented = _prepare_page_image(
        image, auto_orient=auto_orient, tesseract_cmd=cmd
    )
    gray = _pil_to_gray(working)
    v_lines = _detect_line_positions(gray, direction="vertical")
    h_lines = _detect_horizontal_lines_adaptive(gray)

    grid_result: TableOcrResult | None = None
    if len(v_lines) >= MIN_TABLE_COLS - 1 and len(h_lines) >= MIN_TABLE_ROWS - 1:
        grid_result = _ocr_grid_cells(
            gray,
            h_lines,
            v_lines,
            pytesseract,
            page_index=page_index,
            mark_column_only=mark_column_only,
            oriented=oriented,
        )
        if grid_result and _is_plausible_table_text(grid_result.text):
            return grid_result

    if len(v_lines) >= 1 or True:
        # Always try row-strip with ratio fallback for mark column
        result = _ocr_row_strips(
            gray,
            pytesseract,
            page_index=page_index,
            v_lines=v_lines,
            oriented=oriented,
        )
        if result and _is_plausible_table_text(result.text):
            logger.debug(
                "Table OCR row-strip page %d: %d rows (oriented=%s)",
                page_index,
                result.grid_rows,
                oriented,
            )
            return result

    if grid_result and grid_result.text.strip():
        return grid_result

    logger.debug(
        "Table OCR: no result on page %d (h=%d, v=%d, oriented=%s)",
        page_index,
        len(h_lines),
        len(v_lines),
        oriented,
    )
    return None


def ocr_tables_from_pdf(
    pdf_path: Any,
    *,
    dpi: int = TABLE_OCR_DPI,
    pages: list[int] | None = None,
    auto_orient: bool = True,
) -> list[TableOcrResult]:
    """Run table OCR on selected pages of a scanned PDF (1-based page numbers)."""
    from pathlib import Path

    from ..pdf_extractor import _render_pages

    path = Path(pdf_path)
    if not is_cv_available():
        return []

    images = _render_pages(path, dpi=dpi)
    results: list[TableOcrResult] = []
    target_pages = pages or list(range(1, len(images) + 1))

    for page_num in target_pages:
        if page_num < 1 or page_num > len(images):
            continue
        result = ocr_table_from_image(
            images[page_num - 1],
            page_index=page_num - 1,
            auto_orient=auto_orient,
        )
        if result and result.text.strip():
            results.append(result)
            logger.info(
                "Table OCR page %d (%s v%s): %d rows, %d cells, %d chars, oriented=%s",
                page_num,
                result.mode,
                result.version,
                result.grid_rows,
                result.cell_count,
                len(result.text),
                result.oriented,
            )
    return results


def tables_text_from_results(results: list[TableOcrResult]) -> str:
    """Flatten table OCR results into searchable text."""
    parts = [r.text.strip() for r in results if r.text.strip()]
    return "\n\n".join(parts)


def table_ocr_metadata() -> dict[str, Any]:
    return {
        "version": TABLE_OCR_VERSION,
        "dpi": TABLE_OCR_DPI,
        "opencv_available": is_cv_available(),
        "mark_column_index": MARK_COLUMN_INDEX,
        "min_table_rows": MIN_TABLE_ROWS,
        "modes": ["grid", "row_strip"],
        "auto_orient": True,
    }
