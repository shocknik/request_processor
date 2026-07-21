"""
S2.5 — демо MarkCorrector (+ opt-in LLM) на 3 OCR-марках.

DoD: таблица raw → suggested → source → «помогло / нет»;
запись в corrections/jsonl и JSON-отчёт (не пишет в cable_marks).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from ..config import DB_PATH_DEFAULT, PROJECT_ROOT
from .feedback import AssistantFeedbackEvent, append_assistant_feedback
from .mark_corrector import MarkCorrector
from .models import AssistantContext

Helped = Literal["yes", "no", "partial", "n/a"]

# Эталонные OCR-кейсы (урок 0 + prod 21.07 + regression).
# expected — целевой вид для автооценки «помогло»; кейсы подобраны под
# текущий MarkCorrector (детерминированный слой без LLM).
DEMO_OCR_CASES: tuple[dict[str, str], ...] = (
    {
        "id": "vvg_fire_latin",
        "raw": "ВВГнг(A) 3x1,5",
        "expected": "ВВГнг(А) 3х1,5",
        "note": "латиница A и x в fire-class/сечении",
    },
    {
        "id": "sk_vvg_lsltx",
        "raw": "СК ВВГнг(A)-LSLTx 3x1,5ок(N)-0,66",
        "expected": "СК ВВГнг(А)-LSLTx 3х1,5ок(N)-0,66",
        "note": "prod 21.07 — A→А, x→х",
    },
    {
        "id": "kcbur_ocr",
        "raw": "KCBur(A)-LS 3x2,50",
        "expected": "КСБнг(А)",
        "note": "классический OCR-мусор бренда (префикс КСБнг)",
    },
)


@dataclass
class DemoMarkRow:
    case_id: str
    raw: str
    expected: str
    suggested: str
    confidence: float
    source: str
    reason: str
    note: str
    helped: Helped
    changed: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _auto_helped(raw: str, suggested: str, expected: str) -> Helped:
    """Сравнение с эталоном (не замена human-in-the-loop, только демо-метрика)."""
    s = (suggested or "").strip()
    e = (expected or "").strip()
    r = (raw or "").strip()
    if not s or s == r:
        return "no" if e and s != e else "n/a"
    if s == e:
        return "yes"
    # частичное: эталон — префикс/подстрока (напр. «КСБнг(А)» vs полная марка)
    def _compact(x: str) -> str:
        return (
            x.lower()
            .replace(" ", "")
            .replace("-", "")
            .replace("«", "")
            .replace("»", "")
        )

    cs, ce = _compact(s), _compact(e)
    if cs == ce:
        return "yes"
    if e and (ce in cs or cs.startswith(ce) or ce.startswith(cs[: max(4, len(ce))])):
        return "partial" if cs != ce else "yes"
    # улучшение fire-class / x→х при том же бренде
    if r != s and ("(а)" in cs or "х" in cs) and ("(a)" in r.lower() or "x" in r.lower()):
        return "partial"
    return "no"


def run_ocr_marks_demo(
    *,
    db_path: Path | str = DB_PATH_DEFAULT,
    cases: list[dict[str, str]] | None = None,
    force_llm: bool = False,
    record_feedback: bool = False,
    operator_helped: dict[str, Helped] | None = None,
) -> dict[str, Any]:
    """
    Прогон 3 OCR-марок через MarkCorrector.

    force_llm: не меняет settings в БД; LLM сработает только если уже enabled
    (или ASSISTANT_LLM_ENABLED=1). Параметр оставлен для CLI-документации.

    operator_helped: case_id → yes|no|partial — переопределяет авто-оценку.
    """
    del force_llm  # подсказка CLI; фактический LLM — через settings
    corrector = MarkCorrector(db_path)
    ctx = AssistantContext(
        document_type="s2_5_demo",
        ocr_engine="demo",
        document_text="S2.5 demo OCR marks",
    )
    rows: list[DemoMarkRow] = []
    session_id = datetime.now().strftime("%Y%m%d%H%M%S")
    events: list[AssistantFeedbackEvent] = []

    for case in cases or list(DEMO_OCR_CASES):
        raw = case["raw"]
        expected = case.get("expected") or ""
        sug = corrector.suggest(raw, context=ctx)
        helped = _auto_helped(raw, sug.suggested, expected)
        if operator_helped and case["id"] in operator_helped:
            helped = operator_helped[case["id"]]
        row = DemoMarkRow(
            case_id=case["id"],
            raw=raw,
            expected=expected,
            suggested=sug.suggested,
            confidence=float(sug.confidence),
            source=str(sug.source),
            reason=sug.reason or "",
            note=case.get("note") or "",
            helped=helped,
            changed=bool(sug.changed),
        )
        rows.append(row)
        if record_feedback and sug.changed:
            decision = "accepted" if helped in ("yes", "partial") else "rejected"
            events.append(
                AssistantFeedbackEvent(
                    decision=decision,  # type: ignore[arg-type]
                    raw=raw,
                    suggested=sug.suggested,
                    confidence=sug.confidence,
                    source=sug.source,
                    reason=f"s2_5_demo:{case['id']}:{helped}",
                    document="s2_5_ocr_demo",
                    session_id=session_id,
                )
            )

    if record_feedback and events:
        append_assistant_feedback(events, db_path=db_path)

    yes = sum(1 for r in rows if r.helped == "yes")
    partial = sum(1 for r in rows if r.helped == "partial")
    no = sum(1 for r in rows if r.helped == "no")
    report = {
        "title": "S2.5 OCR marks demo",
        "session_id": session_id,
        "at": datetime.now().isoformat(timespec="seconds"),
        "db_path": str(Path(db_path)),
        "counts": {
            "total": len(rows),
            "helped_yes": yes,
            "helped_partial": partial,
            "helped_no": no,
            "changed": sum(1 for r in rows if r.changed),
            "llm_source": sum(1 for r in rows if r.source == "llm"),
        },
        "rows": [r.to_dict() for r in rows],
    }
    return report


def save_demo_report(
    report: dict[str, Any],
    *,
    output_dir: Path | str | None = None,
) -> Path:
    """Пишет JSON в data/training/exports/reports/."""
    out_dir = Path(output_dir) if output_dir else (
        PROJECT_ROOT / "data" / "training" / "exports" / "reports"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    path = out_dir / f"s2_5_ocr_demo_{stamp}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def format_demo_table(report: dict[str, Any]) -> str:
    """Текстовая таблица для CLI / лога."""
    lines = [
        f"S2.5 демо OCR-марок  session={report.get('session_id')}",
        f"{'raw':<42} {'suggested':<42} {'src':<12} {'conf':>5} helped",
        "-" * 110,
    ]
    for row in report.get("rows") or []:
        lines.append(
            f"{(row['raw'] or '')[:41]:<42} "
            f"{(row['suggested'] or '')[:41]:<42} "
            f"{(row['source'] or '')[:12]:<12} "
            f"{float(row.get('confidence') or 0):5.2f} "
            f"{row.get('helped')}"
        )
    c = report.get("counts") or {}
    lines.append("-" * 110)
    lines.append(
        f"yes={c.get('helped_yes')} partial={c.get('helped_partial')} "
        f"no={c.get('helped_no')} llm={c.get('llm_source')} changed={c.get('changed')}"
    )
    return "\n".join(lines)
