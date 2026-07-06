# Создаёт структуру папок для обучения OCR/ассистента.
# См. Obsidian: 35d — Подготовка среды обучения (Windows)

$root = Split-Path -Parent $PSScriptRoot
$dirs = @(
    "data/training/documents/inbox",
    "data/training/documents/registered",
    "data/training/documents/archived",
    "data/training/labels/marks",
    "data/training/labels/organizations",
    "data/training/labels/requirements",
    "data/training/labels/ocr_pages",
    "data/training/rag_corpus/tu",
    "data/training/rag_corpus/protocols",
    "data/training/rag_corpus/gost",
    "data/training/rag_corpus/internal",
    "data/training/rag_corpus/pmi",
    "data/training/exports/jsonl",
    "data/training/exports/reports",
    "data/families"
)

foreach ($rel in $dirs) {
    $path = Join-Path $root $rel
    New-Item -ItemType Directory -Force -Path $path | Out-Null
    Write-Host "OK $rel"
}

Write-Host ""
Write-Host "Done. Add PDFs to data/training/documents/inbox/"