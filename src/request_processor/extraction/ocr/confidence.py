"""
Word-level confidence from Tesseract OCR output.

See Obsidian 35b §4.4 — OcrPageResult.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .preprocess import PREPROCESS_VERSION


@dataclass
class OcrWord:
    text: str
    confidence: float
    left: int = 0
    top: int = 0
    width: int = 0
    height: int = 0


@dataclass
class OcrPageResult:
    text: str
    words: list[OcrWord] = field(default_factory=list)
    engine: str = "tesseract"
    dpi: int = 200
    preprocess_version: str | None = PREPROCESS_VERSION
    mean_confidence: float = 0.0


def parse_tesseract_tsv(tsv: str) -> list[OcrWord]:
    """Parse ``image_to_data`` TSV output into word records."""
    words: list[OcrWord] = []
    lines = tsv.strip().splitlines()
    if len(lines) < 2:
        return words

    for line in lines[1:]:
        parts = line.split("\t")
        if len(parts) < 12:
            continue
        try:
            conf = float(parts[10])
        except ValueError:
            continue
        text = parts[11].strip()
        if conf < 0 or not text:
            continue
        words.append(
            OcrWord(
                text=text,
                confidence=conf / 100.0,
                left=int(parts[6] or 0),
                top=int(parts[7] or 0),
                width=int(parts[8] or 0),
                height=int(parts[9] or 0),
            )
        )
    return words


def mean_word_confidence(words: list[OcrWord]) -> float:
    if not words:
        return 0.0
    return round(sum(w.confidence for w in words) / len(words), 4)


def ocr_image_with_data(
    image: Any,
    pytesseract: Any,
    *,
    lang: str = "rus+eng",
    config: str = "--psm 6 --oem 1",
    dpi: int = 200,
    preprocess_version: str | None = PREPROCESS_VERSION,
) -> OcrPageResult:
    """Run Tesseract and return text plus per-word confidence."""
    text = pytesseract.image_to_string(image, lang=lang, config=config).strip()
    tsv = pytesseract.image_to_data(
        image,
        lang=lang,
        config=config,
        output_type=pytesseract.Output.STRING,
    )
    words = parse_tesseract_tsv(tsv)
    return OcrPageResult(
        text=text,
        words=words,
        engine="tesseract",
        dpi=dpi,
        preprocess_version=preprocess_version,
        mean_confidence=mean_word_confidence(words),
    )