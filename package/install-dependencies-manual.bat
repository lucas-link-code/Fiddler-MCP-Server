@echo off
setlocal enabledelayedexpansion

REM ============================================================================
REM Manual Dependency Installer
REM Use if deploy-mcp.bat fails at the dependency installation step.
REM Prefers requirements-gemini.txt; falls back to per-package installs.
REM ============================================================================

cd /d "%~dp0"

cls
echo ============================================================================
echo   Manual Dependency Installation
echo ============================================================================
echo.
echo This script installs Python packages needed for Gemini, DeepSeek,
echo OpenRouter, MCP bridges, and the Flask session buffer.
echo.
echo Prefer running as Administrator if pip fails with permission errors.
echo.
echo On FLARE / analysis VMs, Python may fail TLS to pypi.org. This installer
echo probes PyPI and retries pip with --trusted-host when needed.
echo.
echo ============================================================================
echo.
pause

echo [Step 1/4] Checking Python installation...
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo Install Python 3.10+ from https://www.python.org/downloads/
    echo Check "Add Python to PATH" during installation
    pause
    exit /b 1
)
for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PY_VERSION=%%i
echo SUCCESS: Python %PY_VERSION% detected

for /f "tokens=1,2 delims=." %%a in ("%PY_VERSION%") do (
    set PY_MAJOR=%%a
    set PY_MINOR=%%b
)
if %PY_MAJOR% LSS 3 goto :BAD_PY_VERSION
if %PY_MAJOR% EQU 3 if %PY_MINOR% LSS 10 goto :BAD_PY_VERSION
echo.
goto :AFTER_PY_CHECK

:BAD_PY_VERSION
echo ERROR: Python 3.10 or later is required. Current: %PY_VERSION%
pause
exit /b 1

:AFTER_PY_CHECK
if not exist "%~dp0pypi_tls.py" (
    echo ERROR: pypi_tls.py not found next to this script.
    echo Keep pypi_tls.py in the same folder as install-dependencies-manual.bat
    pause
    exit /b 1
)

echo [Step 2/4] Upgrading pip...
python "%~dp0pypi_tls.py" install --upgrade pip
if errorlevel 1 (
    echo WARNING: pip upgrade failed, continuing with current pip...
) else (
    echo SUCCESS: pip upgrade command finished
)
echo.

echo [Step 3/4] Installing packages...
if exist "%~dp0requirements-gemini.txt" (
    echo Using requirements-gemini.txt
    python "%~dp0pypi_tls.py" install -r "%~dp0requirements-gemini.txt"
    if errorlevel 1 (
        echo ERROR: requirements-gemini.txt install failed
        echo Falling back to per-package installs...
        goto :FALLBACK_PACKAGES
    )
    goto :VERIFY
)

:FALLBACK_PACKAGES
echo Installing packages one by one...
for %%P in (
    google-generativeai
    openai
    certifi
    httpx
    rich
    mcp
    pydantic
    Flask
    requests
) do (
    echo   Installing %%P...
    python "%~dp0pypi_tls.py" install %%P
    if errorlevel 1 (
        echo ERROR: Failed to install %%P
        pause
        exit /b 1
    )
    echo   SUCCESS: %%P
)

:VERIFY
echo.
echo [Step 4/4] Verifying imports...
set VERIFY_FAILED=0
for %%M in (google.generativeai rich mcp pydantic flask requests openai httpx certifi) do (
    echo Checking %%M...
    python -c "import %%M; print('  OK')" 2>nul
    if errorlevel 1 (
        echo   FAILED: Cannot import %%M
        set VERIFY_FAILED=1
    )
)
echo Checking mcp.server.fastmcp...
python -c "from mcp.server.fastmcp import FastMCP; print('  OK')" 2>nul
if errorlevel 1 (
    echo   FAILED: Cannot import FastMCP from mcp.server.fastmcp
    echo   mcp 2.0 removed FastMCP. Install: python pypi_tls.py install "mcp>=1.0.0,<2.0.0"
    set VERIFY_FAILED=1
)

echo.
if %VERIFY_FAILED% EQU 1 (
    echo WARNING: Some packages failed verification.
    echo Try a new command prompt, or run: python -m pip list
    pause
    exit /b 1
)

echo ============================================================================
echo   SUCCESS: All Dependencies Installed
echo ============================================================================
echo.
echo NEXT STEP: Run deploy-mcp.bat again, or start-fiddler-mcp.bat
echo after a completed first deploy.
echo.
pause
exit /b 0
