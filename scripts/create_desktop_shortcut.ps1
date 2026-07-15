# Создаёт ярлык Lab_request на рабочем столе (иконка приложения, не Python).
# Запуск: powershell -ExecutionPolicy Bypass -File scripts\create_desktop_shortcut.ps1

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Split-Path -Parent $PSScriptRoot)).Path
$PythonW = Join-Path $ProjectRoot ".venv\Scripts\pythonw.exe"
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$IconScript = Join-Path $ProjectRoot "tools\make_app_icon.py"
$IconPath = Join-Path $ProjectRoot "assets\app_icon.ico"
$Desktop = [Environment]::GetFolderPath("Desktop")
$ShortcutName = "Lab_request.lnk"
$ShortcutPath = Join-Path $Desktop $ShortcutName
$LegacyShortcuts = @(
    (Join-Path $Desktop "Испытания кабелей.lnk"),
    (Join-Path $Desktop "Обработка заявок на испытания кабелей.lnk")
)

if (-not (Test-Path $PythonExe)) {
    Write-Error "Не найден $PythonExe. Сначала: powershell -File scripts\install.ps1"
    exit 1
}

if (-not (Test-Path $IconPath)) {
    Write-Host "Создаю иконку приложения..."
    & $PythonExe $IconScript
}
if (-not (Test-Path $IconPath)) {
    Write-Error "Нет иконки: $IconPath"
    exit 1
}
$IconAbs = (Resolve-Path $IconPath).Path

$Launcher = if (Test-Path $PythonW) { (Resolve-Path $PythonW).Path } else { (Resolve-Path $PythonExe).Path }

$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $Launcher
$Shortcut.Arguments = "-m request_processor.ui.gui"
$Shortcut.WorkingDirectory = $ProjectRoot
$Shortcut.WindowStyle = 1
$Shortcut.Description = "Lab_request — заявки, расчёт, КП, пакет документов"
# Абсолютный путь к .ico — иначе Windows показывает иконку Python
$Shortcut.IconLocation = "$IconAbs,0"
$Shortcut.Save()

foreach ($legacy in $LegacyShortcuts) {
    if ((Test-Path $legacy) -and ($legacy -ne $ShortcutPath)) {
        Remove-Item $legacy -Force
        Write-Host "Удалён старый ярлык: $legacy"
    }
}

Write-Host "Ярлык: $ShortcutPath" -ForegroundColor Green
Write-Host "Имя:   Lab_request"
Write-Host "Иконка: $IconAbs"
Write-Host "Цель:  $Launcher -m request_processor.ui.gui"
