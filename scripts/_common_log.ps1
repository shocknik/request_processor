#Requires -Version 5.1
# Shared logging for Lab_request PS1 scripts.
# Dot-source: . "$PSScriptRoot\_common_log.ps1"
# Then: Initialize-RpLog -ProjectRoot $ProjectRoot -ScriptName "install"
#       Write-RpLog "message"
#       Write-RpLog "error detail" -Level ERROR

function Initialize-RpLog {
    param(
        [Parameter(Mandatory = $true)][string]$ProjectRoot,
        [Parameter(Mandatory = $true)][string]$ScriptName
    )
    $script:RpLogProjectRoot = $ProjectRoot
    $script:RpLogScriptName = $ScriptName
    $logDir = Join-Path $ProjectRoot "data\logs"
    if (-not (Test-Path -LiteralPath $logDir)) {
        New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    }
    $stamp = Get-Date -Format "yyyy-MM-dd"
    $script:RpLogFile = Join-Path $logDir ("scripts_" + $stamp + ".log")
    # Also mirror critical lines into app_*.log for one-file handoff to agent
    $script:RpAppLogFile = Join-Path $logDir ("app_" + $stamp + ".log")

    $banner = "=== PS1 start script=$ScriptName root=$ProjectRoot pid=$PID user=$env:USERNAME host=$env:COMPUTERNAME ==="
    Write-RpLog $banner -Level INFO
    Write-RpLog ("PSVersion=" + $PSVersionTable.PSVersion.ToString() + " OS=" + [Environment]::OSVersion.VersionString) -Level INFO
    Write-RpLog ("Culture=" + [System.Globalization.CultureInfo]::CurrentCulture.Name + " UI=" + [System.Globalization.CultureInfo]::CurrentUICulture.Name) -Level INFO
}

function Write-RpLog {
    param(
        [Parameter(Mandatory = $true)][string]$Message,
        [ValidateSet("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")]
        [string]$Level = "INFO"
    )
    $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $name = if ($script:RpLogScriptName) { $script:RpLogScriptName } else { "ps1" }
    $line = "$ts | $Level | scripts.$name | [PS1] $Message"

    if ($script:RpLogFile) {
        try {
            Add-Content -LiteralPath $script:RpLogFile -Value $line -Encoding UTF8 -ErrorAction Stop
        }
        catch {
            # last resort: temp
            try {
                $fallback = Join-Path $env:TEMP "lab_request_scripts.log"
                Add-Content -LiteralPath $fallback -Value $line -Encoding UTF8
            }
            catch { }
        }
    }
    # Mirror WARNING+ into app log so user can send one file
    if ($script:RpAppLogFile -and ($Level -eq "WARNING" -or $Level -eq "ERROR" -or $Level -eq "CRITICAL" -or $Level -eq "INFO")) {
        try {
            Add-Content -LiteralPath $script:RpAppLogFile -Value $line -Encoding UTF8 -ErrorAction SilentlyContinue
        }
        catch { }
    }

    $color = switch ($Level) {
        "ERROR" { "Red" }
        "CRITICAL" { "Red" }
        "WARNING" { "Yellow" }
        "DEBUG" { "DarkGray" }
        default { "Gray" }
    }
    Write-Host $line -ForegroundColor $color
}

function Write-RpLogException {
    param(
        [Parameter(Mandatory = $true)]$ErrorRecord,
        [string]$Context = ""
    )
    $prefix = if ($Context) { "$Context :: " } else { "" }
    Write-RpLog ($prefix + $ErrorRecord.Exception.Message) -Level ERROR
    if ($ErrorRecord.InvocationInfo) {
        $inv = $ErrorRecord.InvocationInfo
        Write-RpLog ("  at " + $inv.ScriptName + ":" + $inv.ScriptLineNumber + " char " + $inv.OffsetInLine) -Level ERROR
        if ($inv.Line) {
            Write-RpLog ("  line: " + $inv.Line.Trim()) -Level ERROR
        }
    }
    if ($ErrorRecord.ScriptStackTrace) {
        Write-RpLog ("  stack: " + ($ErrorRecord.ScriptStackTrace -replace "`r?`n", " | ")) -Level ERROR
    }
}

function Invoke-RpLoggedStep {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][scriptblock]$Action
    )
    Write-RpLog "STEP begin: $Name" -Level INFO
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $result = & $Action
        $sw.Stop()
        Write-RpLog ("STEP ok: $Name (" + $sw.ElapsedMilliseconds + " ms)") -Level INFO
        return $result
    }
    catch {
        $sw.Stop()
        Write-RpLogException -ErrorRecord $_ -Context "STEP fail: $Name ($($sw.ElapsedMilliseconds) ms)"
        throw
    }
}
