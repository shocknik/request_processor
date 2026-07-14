# Создаёт ярлык на рабочем столе для GUI request-processor.
# Запуск: powershell -ExecutionPolicy Bypass -File scripts\create_desktop_shortcut.ps1

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PythonW = Join-Path $ProjectRoot ".venv\Scripts\pythonw.exe"
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$IconScript = Join-Path $ProjectRoot "tools\make_app_icon.py"
$IconPath = Join-Path $ProjectRoot "assets\app_icon.ico"
$Desktop = [Environment]::GetFolderPath("Desktop")
$ShortcutName = "Обработка заявок на испытания кабелей.lnk"
$ShortcutPath = Join-Path $Desktop $ShortcutName
$LegacyShortcut = Join-Path $Desktop "Испытания кабелей.lnk"

if (-not (Test-Path $PythonExe)) {
    Write-Error "Не найден $PythonExe. Сначала: powershell -File scripts\install.ps1"
    exit 1
}

if (-not (Test-Path $IconPath)) {
    Write-Host "Создаю иконку приложения..."
    & $PythonExe $IconScript
}

$Launcher = if (Test-Path $PythonW) { $PythonW } else { $PythonExe }

$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $Launcher
$Shortcut.Arguments = "-m request_processor.ui.gui"
$Shortcut.WorkingDirectory = $ProjectRoot
$Shortcut.WindowStyle = 1
$Shortcut.Description = "Обработка заявок на испытания кабелей: расчет, КП, пакет документов"
if (Test-Path $IconPath) {
    $Shortcut.IconLocation = "$IconPath,0"
}
$Shortcut.Save()

if ((Test-Path $LegacyShortcut) -and ($LegacyShortcut -ne $ShortcutPath)) {
    Remove-Item $LegacyShortcut -Force
    Write-Host "Удалён старый ярлык: $LegacyShortcut"
}

Write-Host "Ярлык создан: $ShortcutPath" -ForegroundColor Green
Write-Host "Запуск: $Launcher -m request_processor.ui.gui"
if (Test-Path $IconPath) {
    Write-Host "Иконка: $IconPath"
}