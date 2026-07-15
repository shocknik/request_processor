# Запуск protocol_generator на JSON из request-processor.
# Пример:
#   powershell -ExecutionPolicy Bypass -File scripts\run_protocol_from_json.ps1 -JsonPath "D:\...\protocol_meta_order1.json"
#
# protocol_generator по умолчанию: D:\My_projects\protocol_generator

param(
    [Parameter(Mandatory = $true)]
    [string]$JsonPath,
    [string]$ProtocolRoot = "D:\My_projects\protocol_generator"
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $JsonPath)) {
    Write-Error "JSON не найден: $JsonPath"
    exit 1
}
if (-not (Test-Path $ProtocolRoot)) {
    Write-Error "protocol_generator не найден: $ProtocolRoot"
    exit 1
}

$py = Join-Path $ProtocolRoot "venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    $py = Join-Path $ProtocolRoot ".venv\Scripts\python.exe"
}
if (-not (Test-Path $py)) {
    Write-Error "Python venv protocol_generator не найден (venv или .venv)"
    exit 1
}

$jsonAbs = (Resolve-Path $JsonPath).Path
Write-Host "JSON: $jsonAbs"
Write-Host "PG:   $ProtocolRoot"
Set-Location $ProtocolRoot
& $py main.py $jsonAbs
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
