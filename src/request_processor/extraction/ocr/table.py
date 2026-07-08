"""
Table OCR v0: detect grid lines on scanned pages, OCR per cell.

Strategies:
1. Full grid — OpenCV H/V lines → per-cell Tesseract (PSM 7).
2. Row-strip fallback — when horizontal lines are missing (common on Word-export scans),
   OCR the mark-name column band-by-band via text projection.

See Obsidian 35b §4.3, 35s — Table OCR v0.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .preprocess import is_cv_available, preprocess_for_ocr

if TYPE_CHECKING:
    from PIL import Image

logger = logging.getLogger(__name__)

TABLE_OCR_VERSION = "v0"
MIN_TABLE_ROWS = 3
MIN_TABLE_COLS = 2
MIN_LINE_SPAN_RATIO = 0.35
H_LINE_FALLBACK_RATIOS = (0.35, 0.2, 0.12, 0.08)
CELL_PADDING_PX = 4
MARK_COLUMN_INDEX = 1
ROW_STRIP_MIN_HEIGHT = 14
ROW_STRIP_MAX_HEIGHT = 100
ROW_MERGE_GAP_PX = 18


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
    """Guess the mark-name column (2nd column in FLEXICORE-style tables)."""
    edges = _major_vertical_edges(v_lines, width=width)
    if len(edges) >= 3:
        return edges[1], edges[2]
    if len(edges) == 2:
        mid = (edges[0] + edges[1]) // 2
        return edges[0], mid
    return int(width * 0.08), int(width * 0.42)


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


def _ocr_cell_image(cell_gray: Any, pytesseract: Any, *, psm: int = 7) -> str:
    from PIL import Image

    pil = Image.fromarray(cell_gray)
    # Cells are already cropped — skip upscale to avoid multi-megapixel images.
    pil = preprocess_for_ocr(pil, upscale=False, adaptive_threshold=True)
    config = f"--psm {psm} --oem 1"
    text = pytesseract.image_to_string(pil, lang="rus+eng", config=config)
    return re.sub(r"\s+", " ", text).strip()


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
        text = _ocr_cell_image(cell_img, pytesseract)
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
    )


def _is_plausible_table_text(text: str) -> bool:
    """Reject garbage grid OCR (punctuation-only cells)."""
    cleaned = re.sub(r"[^\wА-Яа-яЁё]+", " ", text, flags=re.UNICODE)
    words = [w for w in cleaned.split() if len(w) >= 3]
    return len(text.strip()) >= 30 and len(words) >= 2


def _ocr_row_strips(
    gray: Any,
    pytesseract: Any,
    *,
    page_index: int,
    v_lines: list[int],
) -> TableOcrResult | None:
    """Fallback: OCR mark column row-by-row when horizontal grid lines are weak."""
    h, w = gray.shape[:2]
    x0, x1 = _infer_mark_column_bounds(v_lines, width=w)
    y0 = int(h * 0.12)
    y1 = int(h * 0.92)
    roi = gray[y0:y1, x0:x1]
    bands = _detect_text_row_bands(roi)
    if len(bands) < MIN_TABLE_ROWS:
        return None

    rows: list[list[str]] = []
    cell_count = 0
    for band_y0, band_y1 in bands:
        strip = roi[band_y0:band_y1]
        text = _ocr_cell_image(strip, pytesseract, psm=7)
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
    )


def ocr_table_from_image(
    image: Image.Image,
    *,
    page_index: int = 0,
    mark_column_only: bool = True,
) -> TableOcrResult | None:
    """
    Detect table structure on a page image and OCR mark cells.

    Tries full grid first; falls back to row-strip OCR in the mark column.
    """
    if not is_cv_available():
        logger.debug("Table OCR skipped — OpenCV not installed")
        return None

    import pytesseract

    if not _find_tesseract(pytesseract):
        logger.warning("Table OCR skipped — Tesseract not found")
        return None

    gray = _pil_to_gray(image)
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
        )
        if grid_result and _is_plausible_table_text(grid_result.text):
            return grid_result

    if len(v_lines) >= 1:
        result = _ocr_row_strips(
            gray,
            pytesseract,
            page_index=page_index,
            v_lines=v_lines,
        )
        if result and _is_plausible_table_text(result.text):
            logger.debug(
                "Table OCR row-strip page %d: %d rows",
                page_index,
                result.grid_rows,
            )
            return result

    if grid_result and grid_result.text.strip():
        return grid_result

    logger.debug(
        "Table OCR: no result on page %d (h=%d, v=%d)",
        page_index,
        len(h_lines),
        len(v_lines),
    )
    return None


def ocr_tables_from_pdf(
    pdf_path: Any,
    *,
    dpi: int = 300,
    pages: list[int] | None = None,
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
        result = ocr_table_from_image(images[page_num - 1], page_index=page_num - 1)
        if result and result.text.strip():
            results.append(result)
            logger.info(
                "Table OCR page %d (%s): %d rows, %d cells, %d chars",
                page_num,
                result.mode,
                result.grid_rows,
                result.cell_count,
                len(result.text),
            )
    return results


def tables_text_from_results(results: list[TableOcrResult]) -> str:
    """Flatten table OCR results into searchable text."""
    parts = [r.text.strip() for r in results if r.text.strip()]
    return "\n\n".join(parts)


def table_ocr_metadata() -> dict[str, Any]:
    return {
        "version": TABLE_OCR_VERSION,
        "opencv_available": is_cv_available(),
        "mark_column_index": MARK_COLUMN_INDEX,
        "min_table_rows": MIN_TABLE_ROWS,
        "modes": ["grid", "row_strip"],
    }