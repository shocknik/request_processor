"""Спринт B: fuzzy snap + журнал принять/отклонить."""

from __future__ import annotations

from pathlib import Path

from request_processor.assistant.feedback import (
    AssistantFeedbackEvent,
    append_assistant_feedback,
    list_recent_assistant_feedback,
)
from request_processor.assistant.fuzzy_match import fuzzy_snap_mark, similarity
from request_processor.assistant.mark_corrector import MarkCorrector, suggest_mark_correction
from request_processor.persistence.sqlite_repo import init_db


def test_similarity_identical() -> None:
    assert similarity("ВВГнг(А)-LS 3х1,5", "ВВГнг(А)-LS 3х1,5") == 1.0


def test_fuzzy_snap_finds_close_mark() -> None:
    pool = {
        "ВВГнг(А)-LS 3х1,5",
        "ПВСнг(А)-LS 3х2,5",
        "КСБнг(А)-FRLS 4х1,5",
    }
    # почти эталон (OCR: x вместо х, пробел)
    hit, score = fuzzy_snap_mark("ВВГнг(А)-LS 3x1,5", pool, min_score=0.80)
    assert hit == "ВВГнг(А)-LS 3х1,5"
    assert score >= 0.80


def test_kcbur_still_corrected() -> None:
    result = suggest_mark_correction("KCBur(A)-LS 3x2,50")
    assert result.changed
    assert "КСБ" in result.suggested or "нг" in result.suggested


def test_feedback_jsonl_and_db(tmp_path: Path) -> None:
    db = tmp_path / "fb.db"
    init_db(db)
    corr = tmp_path / "corrections"
    events = [
        AssistantFeedbackEvent(
            decision="accepted",
            raw="KCBur(A) 3x2,5",
            suggested="КСБнг(А) 3х2,5",
            confidence=0.9,
            source="deterministic",
            reason="test",
            document="letter.pdf",
            session_id="sess1",
        ),
        AssistantFeedbackEvent(
            decision="rejected",
            raw="XXX 1х1",
            suggested="ВВГ 1х1",
            confidence=0.7,
            source="brand_db",
            document="letter.pdf",
            session_id="sess1",
        ),
    ]
    path = append_assistant_feedback(events, corrections_dir=corr, db_path=db)
    assert path is not None
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "assistant_accepted" in text or "accepted" in text
    assert "КСБнг" in text

    rows = list_recent_assistant_feedback(limit=10, db_path=db)
    assert len(rows) >= 2
    decisions = {r.get("feedback") for r in rows}
    assert "accepted" in decisions
    assert "rejected" in decisions


def test_mark_corrector_suggest_many(tmp_path: Path) -> None:
    db = tmp_path / "c.db"
    init_db(db)
    mc = MarkCorrector(db)
    many = mc.suggest_many(
        ["KCBur(A)-LS 3x2,50", "ВВГнг(А)-LS 3х1,5"],
        only_changed=True,
    )
    assert any(s.changed for s in many)
