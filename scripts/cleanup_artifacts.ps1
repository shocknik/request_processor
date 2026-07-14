# Безопасная уборка регенерируемых артефактов (не трогает registered/, rag_corpus/, app.db).
# См. Obsidian: 35k — Корпус ГОСТ и уборка артефактов

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$removed = 0

foreach ($dir in @("terminals", "agent-tools", "build", "out", "dist")) {
    $path = Join-Path $root $dir
    if (Test-Path $path) {
        Remove-Item -Recurse -Force $path
        Write-Host "Removed: $dir/"
        $removed++
    }
}

# Установщики OCR (не в git, см. .gitignore tools/*.exe)
$tools = Join-Path $root "tools"
if (Test-Path $tools) {
    Get-ChildItem $tools -Filter "*.exe" -File -ErrorAction SilentlyContinue | ForEach-Object {
        Remove-Item $_.FullName -Force
        Write-Host "Removed: tools/$($_.Name)"
        $removed++
    }
}

# __pycache__ только в src/ и tests/ (не .venv)
foreach ($dir in @("src", "tests")) {
    $base = Join-Path $root $dir
    if (Test-Path $base) {
        Get-ChildItem $base -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue | ForEach-Object {
            Remove-Item -Recurse -Force $_.FullName
            Write-Host "Removed: $($_.FullName.Replace($root + '\', ''))"
            $removed++
        }
    }
}

$reports = Join-Path $root "data\training\exports\reports"
if (Test-Path $reports) {
    Get-ChildItem $reports -Filter "*_run1.json" -File | ForEach-Object {
        Remove-Item $_.FullName -Force
        Write-Host "Removed: $($_.Name)"
        $removed++
    }
    foreach ($extra in @("test_run.json")) {
        $p = Join-Path $reports $extra
        if (Test-Path $p) {
            Remove-Item $p -Force
            Write-Host "Removed: $extra"
            $removed++
        }
    }
}

Write-Host ""
Write-Host "Done. Removed items: $removed"
Write-Host "Kept: inbox_batch_summary.json, data/training/documents/registered/, rag_corpus/, data/app.db"