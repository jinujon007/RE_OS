@echo off
REM RE_OS — One-click launcher (Command Prompt / CMD)
REM Usage:
REM   run.bat                    → full sweep (all markets)
REM   run.bat Yelahanka          → single market
REM   run.bat Devanahalli
REM   run.bat history            → show last 10 run attempts
REM
REM Just double-click run.bat or type: run.bat [market]

setlocal enabledelayedexpansion
cd /d "%~dp0"

set "MARKET=%~1"
set "WIDTH==================================================================="

echo.
echo %WIDTH%
echo   RE_OS -- Market Intelligence System
echo %WIDTH%
echo.

REM ── Preflight: Docker ──────────────────────────────────────────────────────
echo   ^>^> Checking Docker stack ...
docker compose ps --status running -q >nul 2>&1
if errorlevel 1 (
    echo   ^>^> Stack not up -- starting Docker Compose ...
    docker compose up -d
    echo   ^>^> Waiting 15s for services to initialise ...
    timeout /t 15 /nobreak >nul
) else (
    echo   OK  Docker stack is running
)

REM ── Check Ollama model ──────────────────────────────────────────────────────
echo   ^>^> Checking Ollama model (llama3.1:8b) ...
docker compose exec ollama ollama list 2>&1 | findstr "llama3.1:8b" >nul
if errorlevel 1 (
    echo   ^>^> Pulling llama3.1:8b -- first time only, takes a few minutes ...
    docker compose exec ollama ollama pull llama3.1:8b
) else (
    echo   OK  Ollama llama3.1:8b ready
)

echo.

REM ── Run history shortcut ────────────────────────────────────────────────────
if /i "%MARKET%"=="history" (
    echo   ^>^> Showing last 10 run attempts ...
    docker compose exec agents python config/run_logger.py
    goto :end
)

REM ── Run the crew ────────────────────────────────────────────────────────────
if "%MARKET%"=="" (
    echo   ^>^> Running full market sweep (all configured markets) ...
    echo   You will see live stage banners as each agent completes.
    echo.
    docker compose exec agents python crews/market_intel_crew.py
) else (
    echo   ^>^> Running market intelligence for: %MARKET%
    echo   You will see live stage banners as each agent completes.
    echo.
    docker compose exec agents python crews/market_intel_crew.py --market %MARKET%
)

REM ── Summary ─────────────────────────────────────────────────────────────────
echo.
echo   ^>^> Run history (last 5):
docker compose exec agents python config/run_logger.py 2>nul

echo.
echo   Reports saved in: outputs/
echo   Full log        : logs/runs_summary.md
echo.

:end
endlocal
pause
