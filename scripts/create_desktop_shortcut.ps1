#Requires -Version 5.1
# Creates Lab_request desktop shortcut with a reliable local icon.
# Safe for Windows PowerShell 5.1: no Cyrillic string literals.
# Run: powershell -ExecutionPolicy Bypass -File scripts\create_desktop_shortcut.ps1
#
# Why copy icon to %LOCALAPPDATA%?
# On network installs (W:\...) Explorer often shows a blank/generic shortcut icon
# when IconLocation points to a UNC/mapped-drive path. Local copy fixes that.

$ErrorActionPreference = "Stop"

$ProjectRoot = (Resolve-Path (Split-Path -Parent $PSScriptRoot)).Path
. (Join-Path $PSScriptRoot "_common_log.ps1")
Initialize-RpLog -ProjectRoot $ProjectRoot -ScriptName "create_desktop_shortcut"

$PythonW = Join-Path $ProjectRoot ".venv\Scripts\pythonw.exe"
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$IconScript = Join-Path $ProjectRoot "tools\make_app_icon.py"
$IconPath = Join-Path $ProjectRoot "assets\app_icon.ico"
$Desktop = [Environment]::GetFolderPath("Desktop")
$ShortcutName = "Lab_request.lnk"
$ShortcutPath = Join-Path $Desktop $ShortcutName

# Always-local icon store (Explorer-friendly)
$LocalIconDir = Join-Path $env:LOCALAPPDATA "Lab_request"
$LocalIconPath = Join-Path $LocalIconDir "app_icon.ico"

function Get-Utf8String([byte[]]$Bytes) {
    return [System.Text.Encoding]::UTF8.GetString($Bytes)
}
$LegacyShortcuts = @(
    (Join-Path $Desktop (Get-Utf8String ([byte[]](
        0xD0,0x98,0xD1,0x81,0xD0,0xBF,0xD1,0x8B,0xD1,0x82,0xD0,0xB0,0xD0,0xBD,0xD0,0xB8,0xD1,0x8F,0x20,
        0xD0,0xBA,0xD0,0xB0,0xD0,0xB1,0xD0,0xB5,0xD0,0xBB,0xD0,0xB5,0xD0,0xB9,0x2E,0x6C,0x6E,0x6B
    )))),
    (Join-Path $Desktop (Get-Utf8String ([byte[]](
        0xD0,0x9E,0xD0,0xB1,0xD1,0x80,0xD0,0xB0,0xD0,0xB1,0xD0,0xBE,0xD1,0x82,0xD0,0xBA,0xD0,0xB0,0x20,
        0xD0,0xB7,0xD0,0xB0,0xD1,0x8F,0xD0,0xB2,0xD0,0xBE,0xD0,0xBA,0x20,0xD0,0xBD,0xD0,0xB0,0x20,
        0xD0,0xB8,0xD1,0x81,0xD0,0xBF,0xD1,0x8B,0xD1,0x82,0xD0,0xB0,0xD0,0xBD,0xD0,0xB8,0xD1,0x8F,0x20,
        0xD0,0xBA,0xD0,0xB0,0xD0,0xB1,0xD0,0xB5,0xD0,0xBB,0xD0,0xB5,0xD0,0xB9,0x2E,0x6C,0x6E,0x6B
    ))))
)

try {
    if (-not (Test-Path -LiteralPath $PythonExe)) {
        Write-RpLog "Python not found: $PythonExe" -Level ERROR
        Write-Error "Python not found: $PythonExe. Run scripts\install.ps1 first."
        exit 1
    }

    # Rebuild ico if missing or empty (logo may appear after update)
    $needIcon = -not (Test-Path -LiteralPath $IconPath)
    if (-not $needIcon) {
        $len = (Get-Item -LiteralPath $IconPath).Length
        if ($len -lt 1000) { $needIcon = $true }
    }
    if ($needIcon) {
        Write-RpLog "Building app icon via make_app_icon.py" -Level INFO
        Write-Host "Building app icon..."
        & $PythonExe $IconScript
        if ($LASTEXITCODE -ne 0) {
            Write-RpLog "make_app_icon exitcode=$LASTEXITCODE" -Level WARNING
        }
    }
    if (-not (Test-Path -LiteralPath $IconPath)) {
        Write-RpLog "Icon missing: $IconPath" -Level ERROR
        Write-Error "Icon missing: $IconPath"
        exit 1
    }
    $IconAbs = (Resolve-Path -LiteralPath $IconPath).Path

    # Copy to LOCALAPPDATA so Explorer always has a local IconLocation
    if (-not (Test-Path -LiteralPath $LocalIconDir)) {
        New-Item -ItemType Directory -Path $LocalIconDir -Force | Out-Null
    }
    Copy-Item -LiteralPath $IconAbs -Destination $LocalIconPath -Force
    if (-not (Test-Path -LiteralPath $LocalIconPath)) {
        Write-RpLog "Failed to copy icon to $LocalIconPath — using project path" -Level WARNING
        $IconForShortcut = $IconAbs
    } else {
        $IconForShortcut = (Resolve-Path -LiteralPath $LocalIconPath).Path
        Write-RpLog "Local icon: $IconForShortcut" -Level INFO
    }

    $Launcher = if (Test-Path -LiteralPath $PythonW) {
        (Resolve-Path -LiteralPath $PythonW).Path
    } else {
        (Resolve-Path -LiteralPath $PythonExe).Path
    }

    $Description = "Lab_request - cable test requests, cost calc, commercial offer, document pack"
    Write-RpLog "Creating shortcut path=$ShortcutPath launcher=$Launcher" -Level INFO

    # Remove old .lnk first so Explorer reloads the icon cache for this name
    if (Test-Path -LiteralPath $ShortcutPath) {
        Remove-Item -LiteralPath $ShortcutPath -Force -ErrorAction SilentlyContinue
    }

    $WshShell = New-Object -ComObject WScript.Shell
    $Shortcut = $WshShell.CreateShortcut($ShortcutPath)
    $Shortcut.TargetPath = $Launcher
    $Shortcut.Arguments = "-m request_processor.ui.gui"
    $Shortcut.WorkingDirectory = $ProjectRoot
    $Shortcut.WindowStyle = 1
    $Shortcut.Description = $Description
    # Absolute local path + index 0 (required for multi-size ICO)
    $Shortcut.IconLocation = "$IconForShortcut,0"
    $Shortcut.Save()

    # Verify icon was written
    $verify = $WshShell.CreateShortcut($ShortcutPath)
    Write-RpLog ("Shortcut IconLocation=" + $verify.IconLocation) -Level INFO
    if (-not $verify.IconLocation -or ($verify.IconLocation -match "python")) {
        Write-RpLog "Icon may still be wrong; re-save with local ico" -Level WARNING
        $verify.IconLocation = "$IconForShortcut,0"
        $verify.Save()
    }

    foreach ($legacy in $LegacyShortcuts) {
        if ((Test-Path -LiteralPath $legacy) -and ($legacy -ne $ShortcutPath)) {
            Remove-Item -LiteralPath $legacy -Force
            Write-RpLog "Removed legacy shortcut: $legacy" -Level INFO
            Write-Host "Removed legacy shortcut: $legacy"
        }
    }

    Write-RpLog "Shortcut OK: $ShortcutPath icon=$IconForShortcut" -Level INFO
    Write-Host "Shortcut: $ShortcutPath" -ForegroundColor Green
    Write-Host "Name:     Lab_request"
    Write-Host "Icon:     $IconForShortcut"
    Write-Host "Source:   $IconAbs"
    Write-Host "Target:   $Launcher -m request_processor.ui.gui"
}
catch {
    Write-RpLogException -ErrorRecord $_ -Context "create_desktop_shortcut"
    throw
}
