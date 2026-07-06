# Безопасная уборка регенерируемых артефактов (не трогает registered/, rag_corpus/, app.db).
# См. Obsidian: 35k — Корпус ГОСТ и уборка артефактов

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$removed = 0

foreach ($dir in @("terminals", "agent-tools")) {
    $path = Join-Path $root $dir
    if (Test-Path $path) {
        Remove-Item -Recurse -Force $path
        Write-Host "Removed: $dir/"
        $removed++
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
Write-Host "Kept: inbox_batch_summary.json, data/training/documents/registered/, rag_corpus/"