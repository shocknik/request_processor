#Requires -Version 5.1
<#
.SYNOPSIS
  Собирает zip-релиз для установки на другой ПК (без .venv и тяжёлых корпусов).

.DESCRIPTION
  Кладёт в dist/request_processor_<version>.zip исходники, data/templates,
  data/families, скрипты install/start, README. На целевом ПК: распаковать + install.ps1.

.PARAMETER IncludeTrainingCorpus
  Включить data/training/rag_corpus (большой объём). По умолчанию — нет.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\build_release_zip.ps1
#>
param(
    [switch]$IncludeTrainingCorpus
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

# data essentials
$dataStage = Join-Path $stage "data"
New-Item -ItemType Directory -Path $dataStage -Force | Out-Null
foreach ($sub in @("templates", "families")) {
    $src = Join-Path $ProjectRoot "data\$sub"
    if (Test-Path $src) {
        Copy-Item $src (Join-Path $dataStage $sub) -Recurse -Force
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

# tools: ensure README about portable Tesseract (do not overwrite make_app_icon.py)
$toolsDir = Join-Path $stage "tools"
New-Item -ItemType Directory -Path $toolsDir -Force | Out-Null
$toolsReadme = Join-Path $toolsDir "README.md"
if (-not (Test-Path $toolsReadme)) {
@"
# tools/

- ``make_app_icon.py`` — генерация ``assets/app_icon.ico`` для ярлыка
- Сюда же можно положить **portable Tesseract**:

```
tools/Tesseract-OCR/tesseract.exe
tools/Tesseract-OCR/tessdata/rus.traineddata
tools/Tesseract-OCR/tessdata/eng.traineddata
```

Приложение ищет tesseract в этом пути, затем в Program Files.

Установка на целевом ПК:
1. Распакуйте zip
2. Установите Python 3.10+ (если нет)
3. ``powershell -ExecutionPolicy Bypass -File scripts\install.ps1``
4. ``start_gui.bat``
"@ | Set-Content -Path $toolsReadme -Encoding UTF8
}

# INSTALL one-pager
@"
# Установка на рабочий ПК

1. Распакуйте архив в папку (например ``D:\apps\request_processor``).
2. Установите **Python 3.10+** с python.org (галочка Add to PATH).
3. Установите **Tesseract OCR** (rus+eng)  
   https://github.com/UB-Mannheim/tesseract/wiki  
   или скопируйте portable в ``tools\Tesseract-OCR\``.
4. В PowerShell:

``````powershell
cd D:\apps\request_processor
powershell -ExecutionPolicy Bypass -File scripts\install.ps1
``````

5. Запуск: ``start_gui.bat`` или ярлык «Испытания кабелей» на рабочем столе.

## День 1 оператора

- Откройте вкладку **1. Заявка** → Обзор → PDF/Word → **Извлечь** (DPI **400**).
- Проверьте марки; при подсказках ассистента — **Ассистент → применить**.
- **Подтвердить заявку** → **2. Расчёт** → **3. КП** → **4. Заказы** (заявка + пакет).
- Альтернатива: вставьте текст речи заказчика (кнопка «Текст…»).

PyTorch / torch-CV — только эксперимент, default — Tesseract.
"@ | Set-Content -Path (Join-Path $stage "INSTALL.md") -Encoding UTF8

if (Test-Path $zipPath) { Remove-Item $zipPath -Force }
Write-Host "Упаковка $zipPath ..."
Compress-Archive -Path $stage -DestinationPath $zipPath -Force

$sizeMb = [math]::Round((Get-Item $zipPath).Length / 1MB, 2)
Write-Host "OK: $zipPath ($sizeMb MB)" -ForegroundColor Green
Write-Host "Stage: $stage"
