# Пакетный прогон inbox (Фаза 0, мастер-план 35).
# См. Obsidian: 35h — Прогон inbox (фаза 0)

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
& "$root\.venv\Scripts\python.exe" "$root\scripts\batch_extract_inbox.py"
exit $LASTEXITCODE