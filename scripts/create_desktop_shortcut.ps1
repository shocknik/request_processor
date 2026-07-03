# Создаёт ярлык на рабочем столе для запуска GUI request-processor.
# Запуск: powershell -ExecutionPolicy Bypass -File scripts\create_desktop_shortcut.ps1

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$StartBat = Join-Path $ProjectRoot "start_gui.bat"
$Desktop = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $Desktop "Испытания кабелей.lnk"

if (-not (Test-Path $PythonExe)) {
    Write-Error "Не найден $PythonExe. Сначала: py -3.11 -m venv .venv; pip install -e `".[ocr]`""
    exit 1
}

$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $StartBat
$Shortcut.WorkingDirectory = $ProjectRoot
$Shortcut.WindowStyle = 1
$Shortcut.Description = "Обработка заявок на испытания кабелей (request-processor)"
$Shortcut.Save()

Write-Host "Ярлык создан: $ShortcutPath"
Write-Host "Рабочая папка: $ProjectRoot"