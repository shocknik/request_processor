# Установка Ollama с хранением моделей на диск D (не C:).
# Запуск: powershell -ExecutionPolicy Bypass -File scripts\install_ollama.ps1
#
# После установки:
#   1) Перезапустите терминал (PATH)
#   2) ollama pull llama3.2
#   3) В GUI: Настройки → включить LLM → Проверить Ollama

param(
    [string]$ModelsDir = "D:\ollama\models"
)

$ErrorActionPreference = "Stop"

Write-Host "=== Ollama: модели на $ModelsDir ===" -ForegroundColor Cyan

New-Item -ItemType Directory -Force -Path $ModelsDir | Out-Null
[Environment]::SetEnvironmentVariable("OLLAMA_MODELS", $ModelsDir, "User")
$env:OLLAMA_MODELS = $ModelsDir
Write-Host "OLLAMA_MODELS = $ModelsDir (User env)" -ForegroundColor Green

$ollamaExe = Get-Command ollama -ErrorAction SilentlyContinue
if ($ollamaExe) {
    Write-Host "Ollama уже в PATH: $($ollamaExe.Source)" -ForegroundColor Green
} else {
    Write-Host "Ollama не найдена. Установка через winget..." -ForegroundColor Yellow
    winget install --id Ollama.Ollama -e --accept-source-agreements --accept-package-agreements
    if ($LASTEXITCODE -ne 0) {
        Write-Host "winget не сработал. Скачайте установщик: https://ollama.com/download/windows" -ForegroundColor Red
        exit 1
    }
    Write-Host "Перезапустите PowerShell и снова выполните: ollama pull llama3.2" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Дальше:" -ForegroundColor Cyan
Write-Host "  ollama pull llama3.2"
Write-Host "  request-processor assistant-llm-status"
Write-Host "  request-processor assistant-llm-test `"KCBur(A)-LS 3x2,5`" --enable"