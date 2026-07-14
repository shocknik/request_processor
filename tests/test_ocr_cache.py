"""Тесты кэша OCR и выбора движка."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from request_processor.extraction.pdf_extractor import (
    OCR_CACHE_DIR,
    clear_ocr_cache,
    ocr_pdf,
    resolve_ocr_engine,
)


def test_resolve_ocr_engine_returns_known_value() -> None:
    assert resolve_ocr_engine() in ("tesseract", "easyocr", "none")


def test_ocr_cache_hit_skips_engine(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache_dir = tmp_path / "ocr_cache"
    monkeypatch.setattr("request_processor.extraction.pdf_extractor.OCR_CACHE_DIR", cache_dir)

    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4 minimal")

    calls = {"count": 0}

    def fake_tesseract(path: Path, dpi: int = 200, **kwargs: object) -> str:
        calls["count"] += 1
        return "распознанный текст"

    monkeypatch.setattr(
        "request_processor.extraction.pdf_extractor._find_tesseract", lambda: r"C:\tesseract.exe"
    )
    monkeypatch.setattr(
        "request_processor.extraction.pdf_extractor._ocr_with_tesseract", fake_tesseract
    )

    first = ocr_pdf(pdf, dpi=200, use_cache=True)
    second = ocr_pdf(pdf, dpi=200, use_cache=True)

    assert first == second == "распознанный текст"
    assert calls["count"] == 1
    assert list(cache_dir.glob("*.txt"))


def test_ocr_cache_disabled_always_calls_engine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_dir = tmp_path / "ocr_cache"
    monkeypatch.setattr("request_processor.extraction.pdf_extractor.OCR_CACHE_DIR", cache_dir)

    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4 minimal")

    calls = {"count": 0}

    def fake_tesseract(path: Path, dpi: int = 200, **kwargs: object) -> str:
        calls["count"] += 1
        return "текст"

    monkeypatch.setattr(
        "request_processor.extraction.pdf_extractor._find_tesseract", lambda: r"C:\tesseract.exe"
    )
    monkeypatch.setattr(
        "request_processor.extraction.pdf_extractor._ocr_with_tesseract", fake_tesseract
    )

    ocr_pdf(pdf, use_cache=False)
    ocr_pdf(pdf, use_cache=False)

    assert calls["count"] == 2


def test_clear_ocr_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache_dir = tmp_path / "ocr_cache"
    cache_dir.mkdir()
    (cache_dir / "a.txt").write_text("x", encoding="utf-8")
    (cache_dir / "b.txt").write_text("y", encoding="utf-8")
    monkeypatch.setattr("request_processor.extraction.pdf_extractor.OCR_CACHE_DIR", cache_dir)

    removed = clear_ocr_cache()
    assert removed == 2
    assert not list(cache_dir.glob("*.txt"))


def test_easyocr_reader_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    import numpy as np

    import request_processor.extraction.pdf_extractor as pe

    pe._EASYOCR_READER = None
    created = {"count": 0}

    class FakeReader:
        def readtext(self, *_args, **_kwargs):
            # detail=1 format: (bbox, text, conf)
            return [([(0, 0), (10, 0), (10, 10), (0, 10)], "FLEXICORE 100", 0.9)]

    def fake_reader_ctor(*_args, **_kwargs):
        created["count"] += 1
        return FakeReader()

    monkeypatch.setattr("easyocr.Reader", fake_reader_ctor)
    rgb = np.zeros((100, 200, 3), dtype=np.uint8)
    monkeypatch.setattr(pe, "_render_pages", lambda *_a, **_k: [object()])
    monkeypatch.setattr(pe, "_easyocr_prepare_image", lambda _img: rgb)

    pe._ocr_with_easyocr(Path("dummy.pdf"))
    pe._ocr_with_easyocr(Path("dummy2.pdf"))

    assert created["count"] == 1