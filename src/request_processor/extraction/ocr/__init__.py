"""OCR preprocessing, confidence scoring, benchmarking, and table OCR (Phase 2)."""

from .confidence import OcrPageResult, OcrWord, mean_word_confidence, ocr_image_with_data
from .preprocess import PREPROCESS_VERSION, is_cv_available, preprocess_for_ocr
from .table import TABLE_OCR_VERSION, TableOcrResult, ocr_tables_from_pdf, tables_text_from_results

__all__ = [
    "PREPROCESS_VERSION",
    "TABLE_OCR_VERSION",
    "OcrPageResult",
    "OcrWord",
    "TableOcrResult",
    "is_cv_available",
    "mean_word_confidence",
    "ocr_image_with_data",
    "ocr_tables_from_pdf",
    "preprocess_for_ocr",
    "tables_text_from_results",
]