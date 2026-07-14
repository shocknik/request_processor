"""
OpenCV preprocessing for scanned pages before Tesseract OCR.

Pipeline v3: auto-orient (OSD) → grayscale → deskew → denoise → upscale → adaptive threshold.
See Obsidian 35b §4.2, 35s — Table OCR / orientation fix.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import numpy as np
    from PIL import Image

logger = logging.getLogger(__name__)

PREPROCESS_VERSION = "v3"
MIN_HEIGHT_PX = 1500
UPSCALE_TARGET_HEIGHT = 2000
# Tesseract OSD: rotate degrees clockwise to upright. Low threshold — FLEXICORE p.2 is ~34.
OSD_MIN_CONFIDENCE = 12.0


def is_cv_available() -> bool:
    try:
        import cv2  # noqa: F401

        return True
    except ImportError:
        return False


def _pil_to_gray_array(image: Image.Image) -> np.ndarray:
    import numpy as np

    arr = np.array(image.convert("RGB"))
    import cv2

    return cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)


def _gray_to_pil(gray: np.ndarray) -> Image.Image:
    from PIL import Image

    return Image.fromarray(gray)


def _parse_osd(osd_text: str) -> tuple[int, float]:
    """Return (rotate_clockwise_degrees, confidence) from Tesseract OSD output."""
    rotate = 0
    conf = 0.0
    m_rot = re.search(r"Rotate:\s*(\d+)", osd_text)
    m_conf = re.search(r"Orientation confidence:\s*([\d.]+)", osd_text)
    if m_rot:
        rotate = int(m_rot.group(1)) % 360
    if m_conf:
        conf = float(m_conf.group(1))
    return rotate, conf


def correct_orientation(
    image: Image.Image,
    *,
    min_confidence: float = OSD_MIN_CONFIDENCE,
    tesseract_cmd: str | None = None,
) -> Image.Image:
    """
    Rotate page to upright using Tesseract OSD when confidence is sufficient.

    OSD ``Rotate`` is degrees clockwise needed to correct the page.
    PIL ``rotate`` is counter-clockwise → apply ``-rotate``.
    """
    try:
        import pytesseract
    except ImportError:
        return image

    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    try:
        osd = pytesseract.image_to_osd(image)
    except Exception as exc:
        logger.debug("OSD failed: %s", exc)
        return image

    rotate_cw, conf = _parse_osd(osd)
    if rotate_cw == 0 or conf < min_confidence:
        return image

    logger.info(
        "Auto-orient: rotate %d° CW (OSD conf=%.1f)",
        rotate_cw,
        conf,
    )
    # expand=True so landscape tables keep full content after 90° fix
    return image.rotate(-rotate_cw, expand=True)


def _deskew(gray: np.ndarray, *, max_angle: float = 5.0) -> np.ndarray:
    import cv2
    import numpy as np

    inverted = cv2.bitwise_not(gray) if gray.mean() > 127 else gray.copy()
    coords = np.column_stack(np.where(inverted > 0))
    if len(coords) < 500:
        return gray
    rect = cv2.minAreaRect(coords)
    angle = rect[-1]
    if angle < -45:
        angle = 90 + angle
    if abs(angle) < 0.3 or abs(angle) > max_angle:
        return gray
    h, w = gray.shape[:2]
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(
        gray,
        matrix,
        (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )


def _upscale_if_needed(gray: np.ndarray, *, min_height: int = MIN_HEIGHT_PX) -> np.ndarray:
    import cv2

    h = gray.shape[0]
    if h >= min_height:
        return gray
    scale = UPSCALE_TARGET_HEIGHT / h
    return cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)


def enhance_contrast(image: Image.Image, *, clip_limit: float = 2.5) -> Image.Image:
    """CLAHE contrast boost for pale table cells (table OCR v1)."""
    if not is_cv_available():
        return image
    import cv2
    import numpy as np
    from PIL import Image

    if isinstance(image, Image.Image):
        gray = _pil_to_gray_array(image)
    else:
        gray = image
    clahe = cv2.createCLAHE(clipLimit=clip_limit, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)
    return Image.fromarray(enhanced)


def preprocess_for_ocr(
    image: Image.Image | np.ndarray,
    *,
    deskew: bool = True,
    denoise: bool = True,
    upscale: bool = True,
    adaptive_threshold: bool = True,
    denoise_h: int = 10,
    block_size: int = 31,
    c_value: int = 15,
    contrast: bool = False,
) -> Image.Image:
    """
    Prepare a page image for OCR.

    Returns the original PIL image unchanged when OpenCV is unavailable.
    Orientation correction is applied separately via ``correct_orientation``.
    """
    if not is_cv_available():
        logger.debug("OpenCV not installed — skipping preprocess")
        if hasattr(image, "convert"):
            return image  # type: ignore[return-value]
        from PIL import Image

        return Image.fromarray(image)

    import cv2
    import numpy as np
    from PIL import Image

    if isinstance(image, Image.Image):
        gray = _pil_to_gray_array(image)
    else:
        gray = image if len(image.shape) == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    if contrast:
        clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
        gray = clahe.apply(gray)
    if deskew:
        gray = _deskew(gray)
    if denoise:
        gray = cv2.fastNlMeansDenoising(gray, None, denoise_h, 7, 21)
    if upscale:
        gray = _upscale_if_needed(gray)

    if adaptive_threshold:
        block = block_size if block_size % 2 == 1 else block_size + 1
        gray = cv2.adaptiveThreshold(
            gray,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            block,
            c_value,
        )

    return _gray_to_pil(gray)


def preprocess_metadata() -> dict[str, Any]:
    """Metadata stored in OCR cache keys and benchmark reports."""
    return {
        "version": PREPROCESS_VERSION,
        "pipeline": [
            "auto_orient",
            "grayscale",
            "deskew",
            "denoise",
            "upscale",
            "adaptive_threshold",
        ],
        "opencv_available": is_cv_available(),
        "min_height_px": MIN_HEIGHT_PX,
        "upscale_target_height": UPSCALE_TARGET_HEIGHT,
        "osd_min_confidence": OSD_MIN_CONFIDENCE,
    }
