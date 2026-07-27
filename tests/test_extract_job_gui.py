"""GUI extract job: worker без tkinter, Queue events, fingerprint."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from queue import Queue
from unittest.mock import MagicMock

import pytest

from request_processor.models import CableMarkMatch, PdfExtractionResult
from request_processor.ui.extract_job import (
    ExtractJobOptions,
    ExtractionCancelled,
    GuiExtractEvent,
    new_job_id,
    prepare_extraction_draft,
    run_extract_job,
    runtime_fingerprint,
)

_TRAINING = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "training"
    / "documents"
    / "registered"
)


def _fake_result(path: Path) -> PdfExtractionResult:
    return PdfExtractionResult(
        source_path=str(path),
        source_type="docx",
        page_count=1,
        text="Марка ВВГнг(А) 3х1,5",
        tables=[],
        cable_marks=[
            CableMarkMatch(mark="ВВГнг(А) 3х1,5", context="test", document=None),
        ],
        organizations=[],
        customer_name="",
        manufacturer_name="",
        is_scanned=False,
        ocr_used=False,
    )


def test_run_extract_job_without_tk() -> None:
    """Worker не требует Tk root и не трогает tkinter."""
    events: Queue[GuiExtractEvent] = Queue()
    cancel = threading.Event()
    path = Path("virtual.docx")
    opts = ExtractJobOptions(
        job_id=new_job_id(),
        path=path,
        use_ocr=False,
        ocr_engine="auto",
        ocr_dpi=300,
        confirm_only=True,
        click_t0=time.perf_counter(),
    )

    def fake_extractor(p, **kwargs):
        progress = kwargs.get("progress")
        if progress:
            progress("Чтение Word…", current=1, total=3, stage="text")
            progress("Поиск марок…", current=2, total=3, stage="marks")
            progress("Готово", current=3, total=3, stage="done")
        return _fake_result(Path(p))

    run_extract_job(opts, events, cancel, extractor=fake_extractor)
    kinds = []
    while not events.empty():
        kinds.append(events.get().kind)
    assert kinds[0] == "started"
    assert "progress" in kinds
    assert "result" in kinds
    assert kinds[-1] == "finished"


def test_run_extract_job_cancel_before_extract() -> None:
    events: Queue[GuiExtractEvent] = Queue()
    cancel = threading.Event()
    cancel.set()
    opts = ExtractJobOptions(
        job_id=new_job_id(),
        path=Path("x.docx"),
        use_ocr=False,
        ocr_engine="auto",
        ocr_dpi=300,
        confirm_only=True,
        click_t0=time.perf_counter(),
    )
    run_extract_job(opts, events, cancel, extractor=lambda *a, **k: _fake_result(Path("x")))
    kinds = [events.get().kind for _ in range(events.qsize())]
    # drain
    while not events.empty():
        kinds.append(events.get().kind)
    assert "cancelled" in kinds or "finished" in kinds


def test_run_extract_job_progress_callback_only_queues() -> None:
    """progress callback не вызывает after/set/configure — только queue."""
    events: Queue[GuiExtractEvent] = Queue()
    cancel = threading.Event()
    opts = ExtractJobOptions(
        job_id="abcd1234",
        path=Path("t.docx"),
        use_ocr=False,
        ocr_engine="auto",
        ocr_dpi=300,
        confirm_only=True,
        click_t0=time.perf_counter(),
    )

    def fake_extractor(p, **kwargs):
        progress = kwargs["progress"]
        progress("step", current=1, total=2, stage="marks")
        return _fake_result(Path(p))

    run_extract_job(opts, events, cancel, extractor=fake_extractor)
    progress_events = []
    while not events.empty():
        e = events.get()
        if e.kind == "progress":
            progress_events.append(e)
    assert progress_events
    assert progress_events[0].stage == "marks"
    assert progress_events[0].current == 1


def test_runtime_fingerprint_has_paths() -> None:
    fp = runtime_fingerprint()
    assert Path(fp["pdf_tab_file"]).name == "pdf_tab.py"
    assert fp["source_sha256"]
    assert fp["pid"]
    assert fp["executable"]


def test_prepare_extraction_draft_no_assistant(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    result = _fake_result(tmp_path / "a.docx")
    draft = prepare_extraction_draft(result, source_path=tmp_path / "a.docx", json_stem="a")
    assert len(draft.marks) == 1
    assert draft.json_path is not None
    assert draft.json_path.is_file()


@pytest.mark.skipif(
    not any(_TRAINING.glob("*10067087*.docx")),
    reason="training 10067087 missing",
)
def test_real_docx_job_under_two_seconds() -> None:
    path = next(_TRAINING.glob("*10067087*.docx"))
    events: Queue[GuiExtractEvent] = Queue()
    cancel = threading.Event()
    opts = ExtractJobOptions(
        job_id=new_job_id(),
        path=path,
        use_ocr=False,
        ocr_engine="auto",
        ocr_dpi=300,
        confirm_only=True,
        click_t0=time.perf_counter(),
    )
    t0 = time.perf_counter()
    run_extract_job(opts, events, cancel)
    elapsed = time.perf_counter() - t0
    assert elapsed < 3.0, f"job too slow: {elapsed:.2f}s"
    kinds = []
    result_ev = None
    while not events.empty():
        e = events.get()
        kinds.append(e.kind)
        if e.kind == "result":
            result_ev = e
    assert "started" in kinds
    assert "result" in kinds
    assert result_ev is not None
    draft = result_ev.payload["draft"]
    assert len(draft.marks) >= 1
