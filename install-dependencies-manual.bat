@echo off
setlocal enabledelayedexpansion

REM ============================================================================
REM Manual Dependency Installer
REM ============================================================================
REM Use this if deploy-mcp.bat fails at the dependency installation step
REM This installs each package individually with full error visibility
REM ============================================================================

cls
echo ============================================================================
echo   Manual Dependency Installation
echo ============================================================================
echo.
echo This script will install each Python package individually.
echo You will see detailed output for each installation.
echo.
echo This should be run as Administrator for best results.
echo.
echo Packages to be installed:
echo   - google-generativeai  (Gemini API client)
echo   - rich                 (Console formatting)
echo   - mcp                  (Model Context Protocol)
echo   - pydantic             (Data validation)
echo   - Flask                (HTTP server framework)
echo   - requests             (HTTP client library)
echo.
echo ============================================================================
echo.
pause

REM Check Python is available
echo [Step 1/8] Checking Python installation...
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed or not in PATH
    echo.
    echo Install Python from: https://www.python.org/downloads/
    echo Make sure to check "Add Python to PATH" during installation
    echo.
    pause
    exit /b 1
)
for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PY_VERSION=%%i
echo SUCCESS: Python %PY_VERSION% detected

REM Check Python version is 3.10+
for /f "tokens=1,2 delims=." %%a in ("%PY_VERSION%") do (
    set PY_MAJOR=%%a
    set PY_MINOR=%%b
)

if %PY_MAJOR% LSS 3 (
    echo ERROR: Python 3.10 or later is required
    echo Current version: %PY_VERSION%
    echo.
    echo The MCP package requires Python 3.10+
    echo Download from: https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

if %PY_MAJOR% EQU 3 if %PY_MINOR% LSS 10 (
    echo ERROR: Python 3.10 or later is required
    echo Current version: %PY_VERSION%
    echo.
    echo The MCP package requires Python 3.10+
    echo Download from: https://www.python.org/downloads/
    echo.
    echo RECOMMENDED: Python 3.11 or 3.12
    echo.
    pause
    exit /b 1
)

echo.

REM Upgrade pip
echo [Step 2/8] Upgrading pip...
python -m pip install --upgrade pip
if errorlevel 1 (
    echo WARNING: pip upgrade failed, but continuing with existing version...
) else (
    echo SUCCESS: pip upgraded
)
echo.

REM Install google-generativeai
echo [Step 3/8] Installing google-generativeai...
python -m pip install google-generativeai
if errorlevel 1 (
    echo ERROR: Failed to install google-generativeai
    echo.
    pause
    exit /b 1
)
echo SUCCESS: google-generativeai installed
echo.

REM Install rich
echo [Step 4/8] Installing rich...
python -m pip install rich
if errorlevel 1 (
    echo ERROR: Failed to install rich
    echo.
    pause
    exit /b 1
)
echo SUCCESS: rich installed
echo.

REM Install mcp
echo [Step 5/8] Installing mcp...
python -m pip install mcp
if errorlevel 1 (
    echo ERROR: Failed to install mcp
    echo.
    pause
    exit /b 1
)
echo SUCCESS: mcp installed
echo.

REM Install pydantic
echo [Step 6/8] Installing pydantic...
python -m pip install pydantic
if errorlevel 1 (
    echo ERROR: Failed to install pydantic
    echo.
    pause
    exit /b 1
)
echo SUCCESS: pydantic installed
echo.

REM Install Flask
echo [Step 7/8] Installing Flask...
python -m pip install Flask
if errorlevel 1 (
    echo ERROR: Failed to install Flask
    echo.
    pause
    exit /b 1
)
echo SUCCESS: Flask installed
echo.

REM Install requests
echo [Step 8/8] Installing requests...
python -m pip install requests
if errorlevel 1 (
    echo ERROR: Failed to install requests
    echo.
    pause
    exit /b 1
)
echo SUCCESS: requests installed
echo.

REM Verify installations
echo ============================================================================
echo   Verifying Installations
echo ============================================================================
echo.

set VERIFY_FAILED=0

echo Checking google-generativeai...
python -c "import google.generativeai; print('  OK: google-generativeai', google.generativeai.__version__)" 2>nul
if errorlevel 1 (
    echo   FAILED: Cannot import google-generativeai
    set VERIFY_FAILED=1
)

echo Checking rich...
python -c "import rich; print('  OK: rich', rich.__version__)" 2>nul
if errorlevel 1 (
    echo   FAILED: Cannot import rich
    set VERIFY_FAILED=1
)

echo Checking mcp...
python -c "import mcp; print('  OK: mcp')" 2>nul
if errorlevel 1 (
    echo   FAILED: Cannot import mcp
    set VERIFY_FAILED=1
)

echo Checking pydantic...
python -c "import pydantic; print('  OK: pydantic', pydantic.__version__)" 2>nul
if errorlevel 1 (
    echo   FAILED: Cannot import pydantic
    set VERIFY_FAILED=1
)

echo Checking Flask...
python -c "import flask; print('  OK: Flask', flask.__version__)" 2>nul
if errorlevel 1 (
    echo   FAILED: Cannot import flask
    set VERIFY_FAILED=1
)

echo Checking requests...
python -c "import requests; print('  OK: requests', requests.__version__)" 2>nul
if errorlevel 1 (
    echo   FAILED: Cannot import requests
    set VERIFY_FAILED=1
)

echo.

if %VERIFY_FAILED% EQU 1 (
    echo ============================================================================
    echo   WARNING: Some packages failed verification
    echo ============================================================================
    echo.
    echo One or more packages installed but cannot be imported.
    echo This may indicate a Python environment issue.
    echo.
    echo Try:
    echo   1. Restart this command prompt and run verification again
    echo   2. Check Python installation for corruption
    echo   3. Try running: python -m pip list
    echo.
    pause
    exit /b 1
)

echo ============================================================================
echo   SUCCESS: All Dependencies Installed
echo ============================================================================
echo.
echo All required packages are installed and working correctly.
echo.
echo NEXT STEP:
echo   Run deploy-mcp.bat again
echo.
echo   The deployment script will skip dependency installation
echo   and proceed directly to configuration.
echo.
echo ============================================================================
pause
exit /b 0
