"""Free-text extract: worker не трогает UI (ТЗ 70, волна A)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("tkinter")

from request_processor.models import PdfExtractionResult
from request_processor.ui.gui import RequestProcessorApp
from request_processor.ui.state import ExtractionDraft


@pytest.fixture
def gui_app(tmp_path: Path):
    try:
        app = RequestProcessorApp(db_path=tmp_path / "ft.db")
    except Exception as exc:  # noqa: BLE001
        if exc.__class__.__name__ == "TclError":
            pytest.skip(str(exc))
        raise
    app.withdraw()
    yield app
    app.destroy()


def test_free_text_present_via_bg_job_on_main(gui_app: RequestProcessorApp) -> None:
    """Имитация: work в фоне, present — через schedule_ui (не из worker-thread)."""
    from request_processor.ui.extract_job import prepare_extraction_draft

    result = PdfExtractionResult(
        source_path="text://customer_speech",
        source_type="text",
        page_count=1,
        text="Никита, добрый день! Кабель КАГЭ. Жду стоимость.",
        tables=[],
        cable_marks=[],
        organizations=[],
        customer_name="",
        manufacturer_name="",
        is_scanned=False,
        ocr_used=False,
    )
    virtual = Path("text_customer_test.txt")
    draft = prepare_extraction_draft(
        result, source_path=virtual, json_stem="text_customer_test"
    )

    # _present_extraction_result / apply UI только на «main» — вызываем напрямую
    gui_app._present_extraction_result(
        result,
        source_path=virtual,
        json_stem="text_customer_test",
        confirm_only=True,
        draft=draft,
    )
    assert gui_app._extraction_draft is not None
    assert gui_app._extraction_confirmed is False
    # черновик без org — поля пустые или path-hint
    assert hasattr(gui_app, "draft_customer_var")


def test_free_text_dialog_shows_parse_button(gui_app: RequestProcessorApp) -> None:
    """Кнопки «Разобрать»/«Отмена» видны (не съедены ScrolledText)."""
    found: dict[str, object] = {}

    def _inspect() -> None:
        for child in gui_app.winfo_children():
            if not isinstance(child, type(gui_app)) and child.winfo_class() == "Toplevel":
                # обход всех потомков
                stack = [child]
                labels: list[str] = []
                while stack:
                    w = stack.pop()
                    try:
                        stack.extend(w.winfo_children())
                    except Exception:  # noqa: BLE001
                        continue
                    try:
                        txt = str(w.cget("text"))
                    except Exception:  # noqa: BLE001
                        txt = ""
                    if txt:
                        labels.append(txt)
                found["labels"] = labels
                try:
                    child.destroy()
                except Exception:  # noqa: BLE001
                    pass
                break
        found["done"] = True

    gui_app._run_extract_free_text()
    gui_app.update_idletasks()
    _inspect()
    labels = found.get("labels") or []
    assert any("Разобрать" in str(x) for x in labels), labels
    assert any("Отмена" in str(x) for x in labels), labels


def test_free_text_worker_payload_without_tk() -> None:
    """worker free-text: extract + prepare_draft — без tkinter."""
    from datetime import datetime

    from request_processor.extraction.pdf_extractor import extract_from_text
    from request_processor.ui.extract_job import prepare_extraction_draft

    raw = "Добрый день! Просим испытания провода МГЛФ по ТУ 16.К05."
    result = extract_from_text(raw, source_label="customer_speech")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    virtual = Path(f"text_customer_{stamp}.txt")
    draft = prepare_extraction_draft(
        result, source_path=virtual, json_stem=f"text_customer_{stamp}"
    )
    assert isinstance(draft, ExtractionDraft)
    assert draft.result.source_type == "text"
    assert "МГЛФ" in (draft.result.text or "")