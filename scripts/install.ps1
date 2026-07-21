#Requires -Version 5.1
<#
.SYNOPSIS
  Установка request-processor на рабочий ПК (Windows).

.DESCRIPTION
  Создаёт .venv, ставит зависимости (без тяжёлого PyTorch по умолчанию),
  проверяет Tesseract, инициализирует data/, ярлык на рабочем столе.

.PARAMETER ProjectRoot
  Корень проекта. По умолчанию — родитель папки scripts/.

.PARAMETER WithOcrExtra
  Установить easyocr/torch (экспериментально, ~1+ ГБ). Не рекомендуется как default.

.PARAMETER SkipShortcut
  Не создавать ярлык на рабочем столе.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\install.ps1
#>
param(
    [string]$ProjectRoot = "",
    [switch]$WithOcrExtra,
    [switch]$SkipShortcut
)

$ErrorActionPreference = "Stop"

if (-not $ProjectRoot) {
    $ProjectRoot = Split-Path -Parent $PSScriptRoot
}
$ProjectRoot = (Resolve-Path $ProjectRoot).Path
Set-Location $ProjectRoot

. (Join-Path $PSScriptRoot "_common_log.ps1")
Initialize-RpLog -ProjectRoot $ProjectRoot -ScriptName "install"
Write-RpLog "install start WithOcrExtra=$WithOcrExtra SkipShortcut=$SkipShortcut" -Level INFO

Write-Host "=== request-processor: установка ===" -ForegroundColor Cyan
Write-Host "Корень: $ProjectRoot"

function Find-Python {
    $candidates = @(
        @{ Cmd = "py"; Args = @("-3.12") },
        @{ Cmd = "py"; Args = @("-3.11") },
        @{ Cmd = "py"; Args = @("-3.10") },
        @{ Cmd = "py"; Args = @("-3") },
        @{ Cmd = "python"; Args = @() }
    )
    foreach ($c in $candidates) {
        try {
            $out = & $c.Cmd @($c.Args + @("-c", "import sys; print(sys.executable); print(f'{sys.version_info.major}.{sys.version_info.minor}')")) 2>$null
            if ($LASTEXITCODE -eq 0 -and $out) {
                $lines = @($out)
                $exe = $lines[0].Trim()
                $ver = $lines[1].Trim()
                $parts = $ver.Split(".")
                $major = [int]$parts[0]; $minor = [int]$parts[1]
                if ($major -gt 3 -or ($major -eq 3 -and $minor -ge 10)) {
                    return @{ Exe = $exe; Ver = $ver; Launcher = $c.Cmd; LauncherArgs = $c.Args }
                }
            }
        } catch { }
    }
    return $null
}

$py = Find-Python
if (-not $py) {
    Write-Host "ERROR: Нужен Python 3.10+ (рекомендуется 3.11/3.12)." -ForegroundColor Red
    Write-Host "Скачайте: https://www.python.org/downloads/  (отметьте Add to PATH)"
    exit 1
}
Write-Host "Python $($py.Ver): $($py.Exe)"

$venvDir = Join-Path $ProjectRoot ".venv"
$venvPy = Join-Path $venvDir "Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Write-Host "Создаю venv..."
    & $py.Exe -m venv $venvDir
    if (-not (Test-Path $venvPy)) {
        Write-RpLog "venv create failed" -Level ERROR; Write-Error "Не удалось создать .venv"
        exit 1
    }
} else {
    Write-Host "venv уже есть: $venvDir"
}

Write-Host "Обновляю pip..."
& $venvPy -m pip install --upgrade pip setuptools wheel | Out-Host

$extras = @()
# OpenCV для препроцессинга сканов — лёгкий и полезный
$extras += "cv"
if ($WithOcrExtra) {
    Write-Host "WithOcrExtra: ставлю easyocr (тяжёлый torch)..." -ForegroundColor Yellow
    $extras += "ocr"
}
$extraSpec = if ($extras.Count -gt 0) { ".[" + ($extras -join ",") + "]" } else { "." }

Write-Host "Устанавливаю пакет: pip install -e `"$extraSpec`""
& $venvPy -m pip install -e $extraSpec
if ($LASTEXITCODE -ne 0) {
    Write-RpLog "pip install failed exit=$LASTEXITCODE" -Level ERROR; Write-Error "pip install завершился с ошибкой"
    exit 1
}

# data/
$dataDirs = @(
    "data", "data\generated", "data\extracted", "data\ocr_cache",
    "data\logs", "data\parse_snapshots", "data\templates", "data\families",
    "data\training\corrections"
)
foreach ($d in $dataDirs) {
    $p = Join-Path $ProjectRoot $d
    if (-not (Test-Path $p)) { New-Item -ItemType Directory -Path $p -Force | Out-Null }
}

# Tesseract (пути на рабочем ПК часто другие — env или portable)
$tess = $null
foreach ($envKey in @("TESSERACT_CMD", "TESSERACT_PATH")) {
    $envVal = [Environment]::GetEnvironmentVariable($envKey, "Process")
    if (-not $envVal) { $envVal = [Environment]::GetEnvironmentVariable($envKey, "User") }
    if (-not $envVal) { $envVal = [Environment]::GetEnvironmentVariable($envKey, "Machine") }
    if ($envVal -and (Test-Path $envVal)) {
        $tess = $envVal
        break
    }
}
if (-not $tess) {
    $tessCandidates = @(
        (Join-Path $ProjectRoot "tools\Tesseract-OCR\tesseract.exe"),
        "C:\Program Files\Tesseract-OCR\tesseract.exe",
        "C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        "D:\Tesseract-OCR\tesseract.exe",
        "D:\Apps\Tesseract-OCR\tesseract.exe",
        "D:\Program Files\Tesseract-OCR\tesseract.exe"
    )
    $tess = $tessCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
}
if ($tess) {
    Write-Host "Tesseract: $tess" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "WARNING: Tesseract OCR не найден." -ForegroundColor Yellow
    Write-Host "  Варианты (пути на рабочем ПК могут отличаться от dev):"
    Write-Host "  1) Установить Tesseract (rus+eng) и добавить в PATH"
    Write-Host "  2) Portable: $ProjectRoot\tools\Tesseract-OCR\tesseract.exe"
    Write-Host "  3) Переменная пользователя TESSERACT_CMD = полный путь к tesseract.exe"
    Write-Host "     [Environment]::SetEnvironmentVariable('TESSERACT_CMD', 'D:\path\tesseract.exe', 'User')"
    Write-Host "  https://github.com/UB-Mannheim/tesseract/wiki"
    Write-Host ""
}

# DB init (+ full price catalog seed if test_items empty)
Write-Host "Инициализация БД..."
Write-RpLog "init_db begin" -Level INFO
& $venvPy -c "from request_processor.persistence.sqlite_repo import init_db, ensure_price_catalog, get_all_test_items; init_db(); r=ensure_price_catalog(); n=len(get_all_test_items()); print('DB OK tests=%s source=%s' % (n, r.get('source')))"
if ($LASTEXITCODE -ne 0) {
    Write-RpLog "init_db failed exit=$LASTEXITCODE" -Level WARNING
    Write-Host "WARNING: init_db не прошёл (можно запустить GUI — создаст сама)" -ForegroundColor Yellow
} else {
    Write-RpLog "init_db OK" -Level INFO
}

if (-not $SkipShortcut) {
    $shortcutScript = Join-Path $PSScriptRoot "create_desktop_shortcut.ps1"
    if (Test-Path $shortcutScript) {
        Write-RpLog "running create_desktop_shortcut.ps1" -Level INFO
        & powershell -ExecutionPolicy Bypass -File $shortcutScript
        if ($LASTEXITCODE -ne 0) { Write-RpLog "shortcut script exit=$LASTEXITCODE" -Level WARNING }
    }
}

$priceHint = Join-Path $ProjectRoot "data\Обновленная стоимость на 2026 год.xlsx"
$appDb = Join-Path $ProjectRoot "data\app.db"
$ollamaDefault = Join-Path $env:USERPROFILE ".ollama\models"
Write-Host ""
Write-RpLog "install finished OK" -Level INFO
Write-Host "=== Готово ===" -ForegroundColor Green
Write-Host "Запуск GUI:"
Write-Host "  $ProjectRoot\start_gui.bat"
Write-Host "или ярлык на рабочем столе: Lab_request"
Write-Host ""
Write-Host "Ярлык вручную (если не создался):"
Write-Host "  powershell -ExecutionPolicy Bypass -File scripts\create_desktop_shortcut.ps1"
Write-Host "  (имя: Lab_request.lnk)"
Write-Host ""
if (Test-Path $appDb) {
    Write-Host "БД data\app.db уже есть."
    Write-Host "  Prod-установка с текущим прайсом (очистить только марки/орг.):"
    Write-Host "    .\.venv\Scripts\request-processor.exe prepare-prod-db --yes" -ForegroundColor Cyan
    Write-Host "  (прайс test_items и test_mappings сохраняются; backup app.db.pre_prod_*.db)"
} else {
    Write-Host "Чистая база после install:"
    Write-Host "  • organizations, cable_marks, orders — пустые"
    Write-Host "  • test_items — полный прайс из seed/xlsx (ensure_price_catalog)"
    Write-Host "  • test_mappings — стартовый набор + seed"
    Write-Host "  При необходимости обновить прайс из Excel:"
    if (Test-Path $priceHint) {
        Write-Host "    .\.venv\Scripts\request-processor.exe load-data --price `"$priceHint`"" -ForegroundColor Cyan
    } else {
        Write-Host "    .\.venv\Scripts\request-processor.exe load-data --price data\PRICE.xlsx" -ForegroundColor Yellow
    }
}
Write-Host ""
Write-Host "Ollama (опционально):"
Write-Host "  • URL: http://127.0.0.1:11434"
Write-Host "  • Каталог моделей (стандарт): $ollamaDefault"
Write-Host "  • Модель: ollama pull llama3.2"
Write-Host "  • GUI → 10. Настройки → Проверить Ollama"
Write-Host ""
Write-Host "Рекомендации оператора:"
Write-Host "  • Word (.docx) — основной путь; PDF-сканы: DPI 400"
Write-Host "  • Организации и марки — проверять вручную, затем «Подтвердить заявку»"
Write-Host "  • Раз в неделю: Настройки → Экспорт опыта (zip) → разработчику"
Write-Host ""
