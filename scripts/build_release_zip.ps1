#Requires -Version 5.1
<#
.SYNOPSIS
  Собирает zip-релиз для установки на другой ПК (без .venv и тяжёлых корпусов).

.DESCRIPTION
  Кладёт в dist/request_processor_<version>.zip исходники, data/templates,
  data/families, скрипты install/start, README. На целевом ПК: распаковать + install.ps1.

.PARAMETER IncludeTrainingCorpus
  Включить data/training/rag_corpus (большой объём). По умолчанию — нет.

.PARAMETER IncludeAppDb
  Включить data/app.db как есть. Для prod: сначала
  request-processor prepare-prod-db --yes (прайс остаётся, марки/орг. пустые).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\build_release_zip.ps1
  powershell -ExecutionPolicy Bypass -File scripts\build_release_zip.ps1 -IncludeAppDb
#>
param(
    [switch]$IncludeTrainingCorpus,
    [switch]$IncludeAppDb
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

# version from pyproject
$pyproject = Get-Content (Join-Path $ProjectRoot "pyproject.toml") -Raw
if ($pyproject -match 'version\s*=\s*"([^"]+)"') {
    $version = $Matches[1]
} else {
    $version = "0.0.0"
}

$stamp = Get-Date -Format "yyyyMMdd"
$distDir = Join-Path $ProjectRoot "dist"
$stageName = "request_processor_$version"
$stage = Join-Path $distDir $stageName
$zipPath = Join-Path $distDir "${stageName}_$stamp.zip"

if (Test-Path $stage) { Remove-Item $stage -Recurse -Force }
New-Item -ItemType Directory -Path $stage -Force | Out-Null

$include = @(
    "src",
    "scripts",
    "tests",
    "docs",
    "assets",
    "tools",
    "pyproject.toml",
    "requirements.txt",
    "README.md",
    "INSTALL.md",
    "start_gui.bat",
    "start_gui_debug.bat",
    ".gitignore"
)
# update.ps1 входит в scripts/ — на целевом ПК: scripts\update.ps1

foreach ($item in $include) {
    $src = Join-Path $ProjectRoot $item
    if (-not (Test-Path $src)) { continue }
    $dst = Join-Path $stage $item
    if (Test-Path $src -PathType Container) {
        Copy-Item $src $dst -Recurse -Force
    } else {
        $parent = Split-Path $dst -Parent
        if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
        Copy-Item $src $dst -Force
    }
}

# data essentials (без app.db, ocr_cache, training corpus, generated)
$dataStage = Join-Path $stage "data"
New-Item -ItemType Directory -Path $dataStage -Force | Out-Null
foreach ($sub in @("templates", "families")) {
    $src = Join-Path $ProjectRoot "data\$sub"
    if (Test-Path $src) {
        Copy-Item $src (Join-Path $dataStage $sub) -Recurse -Force
    }
}
# Прайс для load-data на чистой БД (если лежит в data/)
Get-ChildItem (Join-Path $ProjectRoot "data") -Filter "*.xlsx" -ErrorAction SilentlyContinue | ForEach-Object {
    Copy-Item $_.FullName (Join-Path $dataStage $_.Name) -Force
    Write-Host "  + data/$($_.Name)"
}
if ($IncludeAppDb) {
    $appDb = Join-Path $ProjectRoot "data\app.db"
    if (Test-Path $appDb) {
        Copy-Item $appDb (Join-Path $dataStage "app.db") -Force
        Write-Host "  + data/app.db (IncludeAppDb)" -ForegroundColor Cyan
    } else {
        Write-Host "  WARNING: IncludeAppDb, но data/app.db нет" -ForegroundColor Yellow
    }
}
# empty dirs for runtime
foreach ($d in @("generated", "extracted", "ocr_cache", "logs", "parse_snapshots", "training\corrections")) {
    $p = Join-Path $dataStage $d
    New-Item -ItemType Directory -Path $p -Force | Out-Null
    Set-Content (Join-Path $p ".gitkeep") ""
}

if ($IncludeTrainingCorpus) {
    $corpus = Join-Path $ProjectRoot "data\training"
    if (Test-Path $corpus) {
        Write-Host "IncludeTrainingCorpus: копирую data/training (может быть долго)..."
        Copy-Item $corpus (Join-Path $dataStage "training") -Recurse -Force
    }
}

# tools: ensure README about portable Tesseract
$toolsDir = Join-Path $stage "tools"
New-Item -ItemType Directory -Path $toolsDir -Force | Out-Null
$toolsReadme = Join-Path $toolsDir "README.md"
if (-not (Test-Path $toolsReadme)) {
    $toolsLines = @(
        "# tools/",
        "",
        "- make_app_icon.py - icon for desktop shortcut",
        "- portable Tesseract may live here:",
        "",
        "  tools/Tesseract-OCR/tesseract.exe",
        "",
        "See INSTALL.md and NACHNITE_ZDES.md in release root."
    )
    Set-Content -Path $toolsReadme -Value $toolsLines -Encoding UTF8
}

# Keep full INSTALL.md from repo root. Write start-here guide.
$startLines = @(
    "# request-processor v$version - release contents",
    "",
    "## Start here (work PC)",
    "",
    "1. **INSTALL.md** (root) - install steps, shortcut, Ollama, Word.",
    "2. **docs/** - application passport:",
    "   - docs/44 - Pasport prilozheniya (v0.9.1).pdf",
    "   - docs/44 - Pasport prilozheniya (v0.9.1).md",
    "   - docs/README.md",
    "3. Install:",
    "",
    "   cd D:\apps\request_processor",
    "   powershell -ExecutionPolicy Bypass -File scripts\install.ps1",
    "",
    "4. If data/app.db is present - load-data is NOT needed (price already in DB).",
    "5. Run: start_gui.bat or desktop shortcut.",
    "",
    "## Archive contents",
    "",
    "- src/, scripts/, tests/ - application",
    "- data/app.db - price + mappings; marks/orgs empty (if IncludeAppDb)",
    "- data/templates, families - Word templates, YAML families",
    "- data/*.xlsx - price Excel backup",
    "- docs/ - passport + README",
    "- INSTALL.md, README.md - install and overview"
)
# Expand version manually
$startLines = $startLines | ForEach-Object { $_.Replace('$version', $version) }
$startHerePath = Join-Path $stage "НАЧНИТЕ_ЗДЕСЬ.md"
Set-Content -Path $startHerePath -Value $startLines -Encoding UTF8
# Also English-safe name for ZIP tools that mangle Cyrillic
Set-Content -Path (Join-Path $stage "START_HERE.md") -Value $startLines -Encoding UTF8

$docsStage = Join-Path $stage "docs"
if (Test-Path $docsStage) {
    $docsFiles = @(Get-ChildItem $docsStage -Recurse -File)
    Write-Host ("  docs count: " + $docsFiles.Count) -ForegroundColor Cyan
    foreach ($f in $docsFiles) {
        Write-Host ("    + docs/" + $f.Name)
    }
} else {
    Write-Host "  WARNING: docs missing from stage" -ForegroundColor Yellow
}

if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
Write-Host ("Packaging " + $zipPath + " ...")
Compress-Archive -Path $stage -DestinationPath $zipPath -Force

$sizeMb = [math]::Round((Get-Item $zipPath).Length / 1MB, 2)
Write-Host ("OK: " + $zipPath + " sizeMB=" + $sizeMb) -ForegroundColor Green
Write-Host ("Stage: " + $stage)
