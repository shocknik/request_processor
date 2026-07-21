#Requires -Version 5.1
<#
.SYNOPSIS
  Обновление Lab_request / request-processor на месте — БЕЗ удаления data/ и без «сноса» проги.

.DESCRIPTION
  Два режима:

  A) SourceRoot — путь к уже распакованному новому релизу (или git clone).
     Копирует код поверх текущей установки, НЕ трогает data/app.db, corrections,
     generated, ocr_cache, lab_profile.yaml, training/…

  B) ZipPath — zip-релиз. Распаковывает во временную папку, затем как A).

  После копирования: pip install -e ., migrate-db, ярлык Lab_request.

.PARAMETER ProjectRoot
  Текущая установка (куда обновляем). По умолчанию — родитель scripts/.

.PARAMETER SourceRoot
  Папка с НОВЫМ кодом (распакованный zip без затирания data).

.PARAMETER ZipPath
  Путь к request_processor_*.zip (альтернатива SourceRoot).

.PARAMETER SkipShortcut
  Не обновлять ярлык.

.PARAMETER WithOcrExtra
  Переустановить easyocr/torch (редко нужно).

.EXAMPLE
  # 1) Распаковали zip рядом, например D:\apps\request_processor_new
  powershell -ExecutionPolicy Bypass -File scripts\update.ps1 -SourceRoot D:\apps\request_processor_new

.EXAMPLE
  # 2) Прямо из zip
  powershell -ExecutionPolicy Bypass -File scripts\update.ps1 -ZipPath D:\inbox\request_processor_0.9.1_20260715.zip
#>
param(
    [string]$ProjectRoot = "",
    [string]$SourceRoot = "",
    [string]$ZipPath = "",
    [switch]$SkipShortcut,
    [switch]$WithOcrExtra
)

$ErrorActionPreference = "Stop"

if (-not $ProjectRoot) {
    $ProjectRoot = Split-Path -Parent $PSScriptRoot
}
$ProjectRoot = (Resolve-Path $ProjectRoot).Path

. (Join-Path $PSScriptRoot "_common_log.ps1")
Initialize-RpLog -ProjectRoot $ProjectRoot -ScriptName "update"
Write-RpLog ("update start ZipPath=" + $ZipPath + " SourceRoot=" + $SourceRoot) -Level INFO

Write-Host "=== Lab_request: обновление на месте ===" -ForegroundColor Cyan
Write-Host "Установка: $ProjectRoot"

# --- resolve source ---
$tempExtract = $null
if ($ZipPath) {
    if (-not (Test-Path $ZipPath)) {
        Write-Error "Zip не найден: $ZipPath"
    }
    $ZipPath = (Resolve-Path $ZipPath).Path
    $tempExtract = Join-Path $env:TEMP ("rp_update_" + [guid]::NewGuid().ToString("N").Substring(0, 8))
    New-Item -ItemType Directory -Path $tempExtract -Force | Out-Null
    Write-Host "Распаковка zip → $tempExtract"
    Expand-Archive -Path $ZipPath -DestinationPath $tempExtract -Force
    # zip содержит request_processor_X.Y.Z\...
    $inner = Get-ChildItem $tempExtract -Directory | Select-Object -First 1
    if (-not $inner) {
        Write-Error "В zip нет корневой папки релиза"
    }
    $SourceRoot = $inner.FullName
    Write-Host "Source (из zip): $SourceRoot"
} elseif ($SourceRoot) {
    $SourceRoot = (Resolve-Path $SourceRoot).Path
} else {
    Write-Error "Укажите -SourceRoot <папка_нового_релиза> или -ZipPath <файл.zip>"
}

if ($SourceRoot -eq $ProjectRoot) {
    Write-Error "SourceRoot совпадает с установкой — укажите папку НОВОГО релиза отдельно"
}

# --- backup critical data ---
$backupDir = Join-Path $ProjectRoot ("data\backups\update_" + (Get-Date -Format "yyyyMMdd_HHmmss"))
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
$dbSrc = Join-Path $ProjectRoot "data\app.db"
if (Test-Path $dbSrc) {
    Copy-Item $dbSrc (Join-Path $backupDir "app.db") -Force
    Write-Host "Backup БД: $backupDir\app.db" -ForegroundColor Green
}
$labProf = Join-Path $ProjectRoot "data\lab_profile.yaml"
if (Test-Path $labProf) {
    Copy-Item $labProf (Join-Path $backupDir "lab_profile.yaml") -Force
}

# --- copy code (never wipe data/) ---
$codeItems = @(
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

foreach ($item in $codeItems) {
    $src = Join-Path $SourceRoot $item
    if (-not (Test-Path $src)) {
        Write-Host "  skip (нет в релизе): $item" -ForegroundColor DarkGray
        continue
    }
    $dst = Join-Path $ProjectRoot $item
    if (Test-Path $src -PathType Container) {
        if (Test-Path $dst) {
            # robocopy-like: mirror code folders but we use Copy-Item -Recurse -Force
            # remove destination code tree first for clean overwrite of deleted files
            Remove-Item $dst -Recurse -Force
        }
        Copy-Item $src $dst -Recurse -Force
        Write-Host "  + $item\" -ForegroundColor Gray
    } else {
        $parent = Split-Path $dst -Parent
        if (-not (Test-Path $parent)) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
        Copy-Item $src $dst -Force
        Write-Host "  + $item" -ForegroundColor Gray
    }
}

# templates / families — только если в релизе новее; не удаляем локальные
foreach ($sub in @("templates", "families")) {
    $src = Join-Path $SourceRoot "data\$sub"
    if (-not (Test-Path $src)) { continue }
    $dst = Join-Path $ProjectRoot "data\$sub"
    New-Item -ItemType Directory -Path $dst -Force | Out-Null
    Copy-Item (Join-Path $src "*") $dst -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "  + data\$sub (merge)" -ForegroundColor Gray
}

# НЕ копируем data/app.db из релиза (сохраняем рабочую БД на prod)
Write-Host "data\app.db — сохранён (не перезаписан)" -ForegroundColor Green

# --- reinstall package into existing venv ---
$venvPy = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Write-Host "venv нет — полный install.ps1…" -ForegroundColor Yellow
    $install = Join-Path $ProjectRoot "scripts\install.ps1"
    $args = @("-ExecutionPolicy", "Bypass", "-File", $install)
    if ($WithOcrExtra) { $args += "-WithOcrExtra" }
    if ($SkipShortcut) { $args += "-SkipShortcut" }
    & powershell @args
} else {
    Write-Host "pip install -e . …"
    $extras = @("cv")
    if ($WithOcrExtra) { $extras += "ocr" }
    $spec = ".[" + ($extras -join ",") + "]"
    & $venvPy -m pip install --upgrade pip setuptools wheel | Out-Host
    & $venvPy -m pip install -e $spec
    if ($LASTEXITCODE -ne 0) {
        Write-Error "pip install завершился с ошибкой"
    }
    Write-Host "migrate-db…"
    & $venvPy -c "from request_processor.persistence.sqlite_repo import migrate_db; migrate_db(); print('migrate OK')"
    if (-not $SkipShortcut) {
        $sc = Join-Path $ProjectRoot "scripts\create_desktop_shortcut.ps1"
        if (Test-Path $sc) {
            Write-RpLog "running create_desktop_shortcut.ps1" -Level INFO
            & powershell -ExecutionPolicy Bypass -File $sc
            if ($LASTEXITCODE -ne 0) { Write-RpLog ("shortcut exit=" + $LASTEXITCODE) -Level WARNING }
        }
    }
}

# cleanup temp
if ($tempExtract -and (Test-Path $tempExtract)) {
    Remove-Item $tempExtract -Recurse -Force -ErrorAction SilentlyContinue
}

Write-Host ""
Write-RpLog "update finished OK" -Level INFO
Write-Host "=== Обновление завершено ===" -ForegroundColor Green
Write-Host "Backup: $backupDir"
Write-Host "Запуск: $ProjectRoot\start_gui.bat  или ярлык Lab_request"
Write-Host ""
Write-Host "Сохранено: data\app.db, corrections, generated, logs, lab_profile, training"
Write-Host "Обновлено: src, scripts, docs, templates/families, зависимости"
Write-Host ""
Write-Host "Если GUI не стартует: start_gui_debug.bat → data\gui_launch.log"
