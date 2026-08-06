@echo off
setlocal enabledelayedexpansion

REM ============================================================================
REM Restart bridge + client after first deploy. Skips deps and CustomRules.
REM 5ire-bridge.py is started by the client as the MCP child process.
REM ============================================================================

cd /d "%~dp0"

echo ============================================================================
echo   Fiddler MCP Start
echo ============================================================================
echo.

if not exist "%~dp0enhanced-bridge.py" (
    echo ERROR: enhanced-bridge.py not found in %~dp0
    pause
    exit /b 1
)
if not exist "%~dp0gemini-fiddler-client.py" (
    echo ERROR: gemini-fiddler-client.py not found in %~dp0
    pause
    exit /b 1
)
if not exist "%~dp05ire-bridge.py" (
    echo ERROR: 5ire-bridge.py not found in %~dp0
    pause
    exit /b 1
)

python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found on PATH
    pause
    exit /b 1
)

echo Starting Enhanced Bridge on port 8081...
start "Fiddler MCP Bridge (Port 8081)" /D "%~dp0" cmd /k python enhanced-bridge.py

echo Waiting for bridge...
timeout /t 3 /nobreak >nul

where curl >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    curl -s --connect-timeout 2 http://127.0.0.1:8081/health >nul 2>&1
    if errorlevel 1 (
        echo WARNING: Bridge health check failed. Check the bridge console.
    ) else (
        echo Bridge is up on port 8081
    )
)

echo Starting Gemini Fiddler Client...
echo Note: 5ire-bridge starts inside the client as the MCP child. No third console.
start "Gemini Fiddler Client" /D "%~dp0" cmd /k python gemini-fiddler-client.py

echo.
echo NEXT: In Fiddler use Rules ^> Reload Script if traffic is not posting.
echo Install dir: %~dp0
echo.
pause
exit /b 0
