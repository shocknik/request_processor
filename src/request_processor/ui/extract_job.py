"""
Потокобезопасный extract job: worker не знает о tkinter.

Main thread: Queue polling + progress dialog.
Worker: extract_from_document + prepare draft → events only.
"""

from __future__ import annotations

import hashlib
import importlib.metadata
import inspect
import logging
import os
import re
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from queue import Queue
from typing import Any, Callable, Literal

from ..models import PdfExtractionResult
from ..validation.extraction_validator import validate_extraction
from .state import ExtractionDraft

_log = logging.getLogger("request_processor.ui.extract_job")

EventKind = Literal[
    "started",
    "progress",
    "result",
    "error",
    "cancelled",
    "finished",
]


class ExtractionCancelled(Exception):
    """Оператор нажал «Отмена»."""


@dataclass(frozen=True, slots=True)
class ExtractJobOptions:
    job_id: str
    path: Path
    use_ocr: bool
    ocr_engine: str
    ocr_dpi: int
    confirm_only: bool
    click_t0: float = 0.0


@dataclass(frozen=True, slots=True)
class GuiExtractEvent:
    job_id: str
    kind: EventKind
    stage: str = ""
    message: str = ""
    current: int | None = None
    total: int | None = None
    payload: Any = None
    elapsed: float = 0.0


def new_job_id() -> str:
    return uuid.uuid4().hex[:8]


def append_extract_trace(job_id: str, stage: str) -> None:
    """Независимый от logging sentinel (line-buffered)."""
    try:
        from ..config import LOGS_DIR

        path = Path(LOGS_DIR) / "gui_extract_trace.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", buffering=1) as stream:
            stream.write(
                f"{datetime.now().isoformat()} "
                f"pid={os.getpid()} "
                f"tid={threading.get_ident()} "
                f"job={job_id} "
                f"stage={stage}\n"
            )
            stream.flush()
    except OSError:
        pass


def log_extract_stage(
    job_id: str,
    started: float,
    stage: str,
    **fields: object,
) -> None:
    _log.info(
        "gui extract job=%s elapsed=%.3fs stage=%s pid=%s thread=%s tid=%s fields=%r",
        job_id,
        time.perf_counter() - started,
        stage,
        os.getpid(),
        threading.current_thread().name,
        threading.get_ident(),
        fields,
        extra={"tag": "ExtractTimeline"},
    )
    append_extract_trace(job_id, stage)


def runtime_fingerprint(*, method: Callable[..., Any] | None = None) -> dict[str, Any]:
    """Путь/хеш реально загруженного кода (не доверять package_version)."""
    import request_processor
    import request_processor.ui.tabs.pdf_tab as pdf_tab_module

    pdf_tab_path = Path(pdf_tab_module.__file__).resolve()
    method_path = pdf_tab_path
    if method is not None:
        try:
            src = inspect.getsourcefile(method) or inspect.getfile(method)
            if src:
                method_path = Path(src).resolve()
        except (TypeError, OSError):
            pass
    try:
        dist_version = importlib.metadata.version("request-processor")
    except importlib.metadata.PackageNotFoundError:
        dist_version = "unknown"
    sha = ""
    mtime_ns = 0
    try:
        raw = method_path.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()[:16]
        mtime_ns = method_path.stat().st_mtime_ns
    except OSError:
        pass
    return {
        "pid": os.getpid(),
        "tid": threading.get_ident(),
        "executable": sys.executable,
        "cwd": str(Path.cwd()),
        "package_file": str(Path(request_processor.__file__).resolve()),
        "pdf_tab_file": str(pdf_tab_path),
        "method_file": str(method_path),
        "dist_version": dist_version,
        "source_mtime_ns": mtime_ns,
        "source_sha256": sha,
        "sys_path0": sys.path[:5],
    }


def log_runtime_fingerprint(*, method: Callable[..., Any] | None = None) -> dict[str, Any]:
    fp = runtime_fingerprint(method=method)
    _log.info(
        "runtime fingerprint pid=%s tid=%s executable=%s cwd=%s "
        "package_file=%s pdf_tab_file=%s method_file=%s "
        "dist_version=%s source_mtime_ns=%s source_sha256=%s sys_path=%r",
        fp["pid"],
        fp["tid"],
        fp["executable"],
        fp["cwd"],
        fp["package_file"],
        fp["pdf_tab_file"],
        fp["method_file"],
        fp["dist_version"],
        fp["source_mtime_ns"],
        fp["source_sha256"],
        fp["sys_path0"],
        extra={"tag": "RuntimeFingerprint"},
    )
    return fp


def install_thread_exception_hook() -> None:
    """Логировать необработанные исключения daemon-потоков."""

    def _hook(args: threading.ExceptHookArgs) -> None:
        _log.critical(
            "thread crash name=%s ident=%s",
            args.thread.name if args.thread else "?",
            args.thread.ident if args.thread else "?",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
            extra={"tag": "ThreadCrash"},
        )

    threading.excepthook = _hook  # type: ignore[assignment]


def prepare_extraction_draft(
    result: PdfExtractionResult,
    *,
    source_path: Path,
    json_stem: str,
) -> ExtractionDraft:
    """Валидация + JSON + ExtractionDraft без tkinter (можно в worker)."""
    report = validate_extraction(result)
    out_dir = Path("data/extracted")
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_stem = re.sub(r'[<>:"/\\|?*]', "_", json_stem)[:80] or "extract"
    out_file = out_dir / f"{safe_stem}.json"
    out_file.write_text(
        result.model_dump_json(indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    initial_marks = [m.model_copy(deep=True) for m in report.marks]
    return ExtractionDraft(
        result=result,
        report=report,
        source_path=source_path,
        json_path=out_file,
        marks=initial_marks,
        original_marks=[m.model_copy(deep=True) for m in initial_marks],
        original_customer=result.customer_name or "",
        original_manufacturer=result.manufacturer_name or "",
    )


def run_extract_job(
    options: ExtractJobOptions,
    events: Queue[GuiExtractEvent],
    cancel_event: threading.Event,
    *,
    extractor: Callable[..., PdfExtractionResult] | None = None,
) -> None:
    """
    Worker entry: только Python/IO. Никакого tkinter / self.after / Variable.

    extractor — для unit-тестов (fake).
    """
    started = options.click_t0 or time.perf_counter()
    # Первая исполняемая строка worker
    append_extract_trace(options.job_id, "worker.entry")
    log_extract_stage(options.job_id, started, "worker.entry")

    def _put(
        kind: EventKind,
        *,
        stage: str = "",
        message: str = "",
        current: int | None = None,
        total: int | None = None,
        payload: Any = None,
    ) -> None:
        events.put(
            GuiExtractEvent(
                job_id=options.job_id,
                kind=kind,
                stage=stage,
                message=message,
                current=current,
                total=total,
                payload=payload,
                elapsed=time.perf_counter() - started,
            )
        )

    _put("started", stage="worker", message="Фоновая обработка запущена")

    try:
        if cancel_event.is_set():
            raise ExtractionCancelled()

        def progress_callback(
            message: str,
            *,
            current: int | None = None,
            total: int | None = None,
            stage: str = "",
        ) -> None:
            if cancel_event.is_set():
                raise ExtractionCancelled()
            _put(
                "progress",
                stage=stage or "work",
                message=message,
                current=current,
                total=total,
            )

        log_extract_stage(options.job_id, started, "extract.import.begin")
        if extractor is None:
            from ..extraction.pdf_extractor import extract_from_document as extractor
        log_extract_stage(options.job_id, started, "extract.import.end")

        if cancel_event.is_set():
            raise ExtractionCancelled()

        log_extract_stage(
            options.job_id,
            started,
            "extract.start",
            file=str(options.path.name),
            use_ocr=options.use_ocr,
            ocr_engine=options.ocr_engine,
        )
        result = extractor(
            options.path,
            use_ocr=options.use_ocr,
            ocr_engine=options.ocr_engine,
            ocr_dpi=options.ocr_dpi,
            progress=progress_callback,
        )
        result = result.model_copy(update={"source_path": str(options.path.resolve())})
        log_extract_stage(
            options.job_id,
            started,
            "extract.done",
            marks=len(result.cable_marks),
            orgs=len(result.organizations),
        )

        if cancel_event.is_set():
            raise ExtractionCancelled()

        log_extract_stage(options.job_id, started, "draft.prepare.start")
        draft = prepare_extraction_draft(
            result,
            source_path=options.path,
            json_stem=options.path.stem,
        )
        log_extract_stage(options.job_id, started, "draft.prepare.end")

        if cancel_event.is_set():
            raise ExtractionCancelled()

        _put(
            "result",
            stage="result",
            message="Готово",
            payload={"result": result, "draft": draft, "confirm_only": options.confirm_only},
        )
    except ExtractionCancelled:
        log_extract_stage(options.job_id, started, "worker.cancelled")
        _put("cancelled", stage="cancelled", message="Отменено")
    except BaseException as exc:
        log_extract_stage(options.job_id, started, "worker.error", error=str(exc))
        _log.exception("extract job failed job=%s", options.job_id)
        _put("error", stage="error", message=str(exc), payload=exc)
    finally:
        elapsed = time.perf_counter() - started
        log_extract_stage(options.job_id, started, "worker.finished", total=elapsed)
        _put("finished", stage="finished", message=f"{elapsed:.3f}")
