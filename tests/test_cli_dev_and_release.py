"""CLI: рабочий день vs разработка; slim-zip для рабочего ПК."""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from request_processor.cli import cli
from request_processor.nlp.nlp_extractor import enhance_organizations, is_nlp_available
from request_processor.models import OrganizationExtract

ROOT = Path(__file__).resolve().parents[1]


def test_cli_help_marks_research_commands() -> None:
    runner = CliRunner()
    root_help = runner.invoke(cli, ["--help"])
    assert root_help.exit_code == 0, root_help.output
    assert "для разработки" in root_help.output
    assert "migrate-db" in root_help.output
    assert "extract-pdf" in root_help.output

    research = runner.invoke(cli, ["ocr-benchmark", "--help"])
    assert research.exit_code == 0, research.output
    assert "[разработка]" in research.output

    rag = runner.invoke(cli, ["index-rag", "--help"])
    assert rag.exit_code == 0, rag.output
    assert "[разработка]" in rag.output

    ops = runner.invoke(cli, ["migrate-db", "--help"])
    assert ops.exit_code == 0, ops.output
    assert "[разработка]" not in ops.output


def test_build_release_zip_has_slim_without_research_scripts() -> None:
    script = (ROOT / "scripts" / "build_release_zip.ps1").read_text(encoding="utf-8")
    assert "[switch]$Slim" in script
    assert "extract_tu_text.py" in script
    assert "install_ollama.ps1" in script
    assert "inventory_tu_corpus.py" in script
    assert "if (-not $Slim)" in script
    assert "$include += \"tests\"" in script
    assert "requirements.txt" not in script


def test_requirements_txt_removed() -> None:
    assert not (ROOT / "requirements.txt").exists()
    assert not (ROOT / "scripts" / "reorganize_packages.py").exists()


def test_nlp_enhance_is_noop_without_torch() -> None:
    orgs = [
        OrganizationExtract(name="ООО «ФаерЛаб»", role="customer", confidence=0.4),
    ]
    if is_nlp_available():
        out = enhance_organizations("заказчик ООО ФаерЛаб", orgs)
        assert isinstance(out, list)
        return
    out = enhance_organizations("заказчик ООО ФаерЛаб", orgs)
    assert out is orgs
