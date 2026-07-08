"""
OpenCV preprocessing for scanned pages before Tesseract OCR.

Pipeline v2: grayscale → deskew → denoise → upscale → adaptive threshold.
See Obsidian 35b §4.2, 35p — Фаза 2.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import numpy as np
    from PIL import Image

logger = logging.getLogger(__name__)

PREPROCESS_VERSION = "v2"
MIN_HEIGHT_PX = 1500
UPSCALE_TARGET_HEIGHT = 2000


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
) -> Image.Image:
    """
    Prepare a page image for OCR.

    Returns the original PIL image unchanged when OpenCV is unavailable.
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
        "pipeline": ["grayscale", "deskew", "denoise", "upscale", "adaptive_threshold"],
        "opencv_available": is_cv_available(),
        "min_height_px": MIN_HEIGHT_PX,
        "upscale_target_height": UPSCALE_TARGET_HEIGHT,
    }