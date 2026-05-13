# RE_OS — One-click launcher (PowerShell)
# Usage:
#   .\run.ps1                          → full sweep (all markets)
#   .\run.ps1 -Market Yelahanka        → single market
#   .\run.ps1 -Market Devanahalli
#   .\run.ps1 -History                 → show last 10 runs
#   .\run.ps1 -Logs                    → tail live log output
#
# Run from the RE_OS folder. Normal or Admin PowerShell both work.

param(
    [string]$Market   = "",
    [switch]$History,
    [switch]$Logs
)

# ── Colours ────────────────────────────────────────────────────────────────────
function Write-Header($msg) {
    Write-Host ""
    Write-Host ("=" * 65) -ForegroundColor Cyan
    Write-Host "  $msg" -ForegroundColor Cyan
    Write-Host ("=" * 65) -ForegroundColor Cyan
    Write-Host ""
}

function Write-Step($msg) {
    Write-Host "  >> $msg" -ForegroundColor Yellow
}

function Write-Ok($msg) {
    Write-Host "  OK  $msg" -ForegroundColor Green
}

function Write-Fail($msg) {
    Write-Host "  ERR $msg" -ForegroundColor Red
}

# ── Locate RE_OS folder ────────────────────────────────────────────────────────
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

# ── Show log tail mode ─────────────────────────────────────────────────────────
if ($Logs) {
    Write-Header "RE_OS — Live Log Tail"
    Write-Step "Tailing logs/crew.log (Ctrl+C to stop)"
    if (Test-Path "logs\crew.log") {
        Get-Content -Path "logs\crew.log" -Wait -Tail 30
    } else {
        Write-Fail "No log file yet. Run the crew first."
    }
    exit 0
}

# ── Show run history ───────────────────────────────────────────────────────────
if ($History) {
    Write-Header "RE_OS — Run History"
    docker compose exec agents python config/run_logger.py
    exit 0
}

# ── Preflight: Docker ──────────────────────────────────────────────────────────
Write-Header "RE_OS — Market Intelligence System"

Write-Step "Checking Docker stack …"
$psOutput = docker compose ps --format json 2>&1
$running  = (docker compose ps --status running -q 2>&1 | Measure-Object -Line).Lines

if ($running -lt 3) {
    Write-Step "Stack not fully up — starting Docker Compose …"
    docker compose up -d
    Write-Step "Waiting 15 s for services to initialise …"
    Start-Sleep -Seconds 15
} else {
    Write-Ok "Docker stack is running ($running containers up)"
}

# ── Check Ollama model ─────────────────────────────────────────────────────────
Write-Step "Checking Ollama model (llama3.1:8b) …"
$ollamaCheck = docker compose exec ollama ollama list 2>&1
if ($ollamaCheck -match "llama3.1:8b") {
    Write-Ok "Ollama llama3.1:8b is ready"
} else {
    Write-Step "Model not found — pulling llama3.1:8b (this takes a few minutes on first run) …"
    docker compose exec ollama ollama pull llama3.1:8b
}

# ── Run the crew ───────────────────────────────────────────────────────────────
Write-Host ""

if ($Market -ne "") {
    Write-Step "Running market intelligence for: $Market"
    Write-Host "  You will see live stage banners as each agent completes." -ForegroundColor DarkGray
    Write-Host ""
    docker compose exec agents python crews/market_intel_crew.py --market $Market
} else {
    Write-Step "Running full market sweep (all configured markets) …"
    Write-Host "  You will see live stage banners as each agent completes." -ForegroundColor DarkGray
    Write-Host ""
    docker compose exec agents python crews/market_intel_crew.py
}

# ── Show run summary ───────────────────────────────────────────────────────────
Write-Host ""
Write-Step "Run history (last 5):"
docker compose exec agents python config/run_logger.py 2>$null | Select-Object -Last 10

Write-Host ""
Write-Host "  Reports saved in: outputs/" -ForegroundColor Green
Write-Host "  Full history    : logs/runs_summary.md" -ForegroundColor Green
Write-Host ""
