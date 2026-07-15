# Установка / проверка Ollama. Модели по умолчанию — стандартный путь Windows.
# Запуск: powershell -ExecutionPolicy Bypass -File scripts\install_ollama.ps1
#
# После установки:
#   1) Перезапустите терминал (PATH)
#   2) ollama pull llama3.2
#   3) В GUI: Настройки → каталог моделей (если не стандартный) → включить LLM → Проверить Ollama

param(
    # Стандарт Ollama на Windows: C:\Users\<User>\.ollama\models
    # Передайте другой путь только если модели лежат не там.
    [string]$ModelsDir = ""
)

$ErrorActionPreference = "Stop"

if (-not $ModelsDir) {
    $ModelsDir = Join-Path $env:USERPROFILE ".ollama\models"
}

Write-Host "=== Ollama: каталог моделей $ModelsDir ===" -ForegroundColor Cyan

New-Item -ItemType Directory -Force -Path $ModelsDir | Out-Null

# Не переопределяем OLLAMA_MODELS, если путь — стандартный ~/.ollama/models
# (Ollama и так туда ходит). Иначе явно указываем нестандартный каталог.
$standard = Join-Path $env:USERPROFILE ".ollama\models"
$isStandard = (Resolve-Path $ModelsDir -ErrorAction SilentlyContinue).Path -eq `
    (Resolve-Path $standard -ErrorAction SilentlyContinue).Path

if (-not $isStandard) {
    [Environment]::SetEnvironmentVariable("OLLAMA_MODELS", $ModelsDir, "User")
    $env:OLLAMA_MODELS = $ModelsDir
    Write-Host "OLLAMA_MODELS = $ModelsDir (User env, нестандартный путь)" -ForegroundColor Green
} else {
    Write-Host "Стандартный путь Ollama — OLLAMA_MODELS не задаём (как у установленной Ollama)." -ForegroundColor Green
    Write-Host "  $ModelsDir"
}

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
Write-Host ""
Write-Host "В GUI → 10. Настройки:"
Write-Host "  Каталог моделей: $ModelsDir"
Write-Host "  Модель: llama3.2"
Write-Host "  URL: http://127.0.0.1:11434"
