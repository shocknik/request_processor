"""Тесты OpenCV preprocess v1 (Фаза 2)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from request_processor.extraction.ocr.confidence import (
    OcrWord,
    mean_word_confidence,
    parse_tesseract_tsv,
)
from request_processor.extraction.ocr.preprocess import (
    PREPROCESS_VERSION,
    is_cv_available,
    preprocess_for_ocr,
    preprocess_metadata,
)


def test_preprocess_metadata() -> None:
    meta = preprocess_metadata()
    assert meta["version"] == PREPROCESS_VERSION
    assert meta["version"] >= "v3"
    assert "grayscale" in meta["pipeline"]
    assert "deskew" in meta["pipeline"]
    assert "auto_orient" in meta["pipeline"]


def test_preprocess_without_opencv_returns_original() -> None:
    from PIL import Image

    img = Image.new("RGB", (40, 20), color=(200, 100, 50))
    with patch("request_processor.extraction.ocr.preprocess.is_cv_available", return_value=False):
        out = preprocess_for_ocr(img)
    assert out.size == img.size


@pytest.mark.skipif(not is_cv_available(), reason="opencv-python-headless not installed")
def test_preprocess_with_opencv_changes_pixels() -> None:
    from PIL import Image

    img = Image.new("RGB", (80, 40), color=(180, 180, 180))
    out = preprocess_for_ocr(img)
    assert out.size[0] >= img.size[0]
    assert out.size != img.size or out.mode != img.mode


def test_parse_tesseract_tsv_and_mean_confidence() -> None:
    tsv = (
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
        "5\t1\t0\t0\t0\t0\t10\t10\t20\t8\t95\tВВГ\n"
        "5\t1\t0\t0\t0\t1\t40\t10\t15\t8\t80\t3х2\n"
    )
    words = parse_tesseract_tsv(tsv)
    assert len(words) == 2
    assert words[0].text == "ВВГ"
    assert words[0].confidence == pytest.approx(0.95)
    assert mean_word_confidence(words) == pytest.approx(0.875)


def test_character_error_rate() -> None:
    from request_processor.extraction.ocr.benchmark import character_error_rate

    assert character_error_rate("abc", "abc") == 0.0
    assert character_error_rate("abd", "abc") == pytest.approx(0.3333, abs=0.001)
    assert character_error_rate("", "abc") == 1.0
    assert character_error_rate("x", "") is None