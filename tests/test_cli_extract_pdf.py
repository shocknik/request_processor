"""Тесты флагов --validate и --dry-run для extract-pdf."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from request_processor.cli import cli
from request_processor.models import PdfExtractionResult

EXTRACTED_DIR = Path(__file__).resolve().parents[1] / "data" / "extracted"


@pytest.fixture
def letter_result() -> PdfExtractionResult:
    path = EXTRACTED_DIR / "Письмо на период. исп. от 04.05.26.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return PdfExtractionResult.model_validate(data)


@pytest.fixture
def blocked_result() -> PdfExtractionResult:
    """Заблокированное извлечение: нет марок, заказчик — испытательный центр."""
    from request_processor.models import OrganizationExtract

    return PdfExtractionResult(
        source_path="blocked.pdf",
        page_count=1,
        text="Генеральному директору\nПросим провести\nмарки: ",
        cable_marks=[],
        organizations=[
            OrganizationExtract(
                name='ООО НИЦ «Кабель-Тест»',
                role="customer",
                org_type="testing_center",
                confidence=0.7,
            )
        ],
        customer_name='ООО НИЦ «Кабель-Тест»',
        ocr_used=True,
        is_scanned=True,
    )


def test_extract_pdf_dry_run_writes_json_skips_db(tmp_path: Path, letter_result: PdfExtractionResult) -> None:
    pdf = tmp_path / "letter.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    out = tmp_path / "out.json"

    with patch(
        "request_processor.cli.extract_from_document",
        return_value=letter_result,
    ):
        with patch("request_processor.cli.save_cable_marks_from_matches") as save_marks:
            with patch("request_processor.cli.save_organizations_from_extraction") as save_orgs:
                with patch("request_processor.cli.save_document_extraction") as save_doc:
                    runner = CliRunner()
                    result = runner.invoke(
                        cli,
                        [
                            "extract-pdf",
                            "--pdf",
                            str(pdf),
                            "--output",
                            str(out),
                            "--dry-run",
                        ],
                    )

    assert result.exit_code == 0, result.output
    assert out.exists()
    assert "dry-run" in result.output.lower() or "пропущена" in result.output
    save_marks.assert_not_called()
    save_orgs.assert_not_called()
    save_doc.assert_not_called()


def test_extract_pdf_validate_prints_report(tmp_path: Path, letter_result: PdfExtractionResult) -> None:
    pdf = tmp_path / "letter.pdf"
    pdf.write_bytes(b"%PDF-1.4")

    with patch(
        "request_processor.cli.extract_from_document",
        return_value=letter_result,
    ):
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["extract-pdf", "--pdf", str(pdf), "--dry-run", "--validate"],
        )

    assert result.exit_code == 0, result.output
    assert "Валидация" in result.output
    assert "Марки (4)" in result.output


def test_extract_pdf_validate_exit_code_on_block(tmp_path: Path, blocked_result: PdfExtractionResult) -> None:
    pdf = tmp_path / "blocked.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    out = tmp_path / "out.json"

    with patch(
        "request_processor.cli.extract_from_document",
        return_value=blocked_result,
    ):
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "extract-pdf",
                "--pdf",
                str(pdf),
                "--output",
                str(out),
                "--dry-run",
                "--validate",
            ],
        )

    assert result.exit_code == 1, result.output
    assert out.exists()
    assert "заблокировано" in result.output.lower() or "P0" in result.output