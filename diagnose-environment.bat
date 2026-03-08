@echo off
setlocal enabledelayedexpansion

REM ============================================================================
REM Fiddler MCP Environment Diagnostic Tool
REM ============================================================================
REM Run this script if deploy-mcp.bat fails during dependency installation
REM This will help identify the root cause of installation failures
REM ============================================================================

cls
echo ============================================================================
echo   Fiddler MCP Environment Diagnostics
echo ============================================================================
echo.
echo Running comprehensive environment checks...
echo This will help identify why dependency installation is failing.
echo.
echo ============================================================================
echo.

REM Test 1: Python Installation
echo [TEST 1] Python Installation
echo ----------------------------------------
python --version 2>nul
if errorlevel 1 (
    echo FAILED: Python is not installed or not in PATH
    echo.
    echo SOLUTION:
    echo   1. Download Python 3.10 or later from https://www.python.org/downloads/
    echo   2. RECOMMENDED: Python 3.11 or 3.12
    echo   3. During installation, CHECK "Add Python to PATH"
    echo   4. Restart computer after installation
    echo.
    goto :TEST_FAILED
) else (
    for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYTHON_VER=%%i
    
    REM Check if version is 3.10+
    for /f "tokens=1,2 delims=." %%a in ("!PYTHON_VER!") do (
        set PY_MAJOR=%%a
        set PY_MINOR=%%b
    )
    
    set VERSION_OK=0
    if !PY_MAJOR! GTR 3 set VERSION_OK=1
    if !PY_MAJOR! EQU 3 if !PY_MINOR! GEQ 10 set VERSION_OK=1
    
    if !VERSION_OK! EQU 0 (
        echo FAILED: Python !PYTHON_VER! is too old
        echo.
        echo REQUIRED: Python 3.10 or later
        echo CURRENT: Python !PYTHON_VER!
        echo.
        echo The MCP package requires Python 3.10+
        echo.
        echo SOLUTION:
        echo   Download Python 3.11 or 3.12 from https://www.python.org/downloads/
        echo.
        goto :TEST_FAILED
    ) else (
        echo SUCCESS: Python !PYTHON_VER! detected (meets 3.10+ requirement)
    )
)
echo.

REM Test 2: Python Executable Location
echo [TEST 2] Python Executable Location
echo ----------------------------------------
where python 2>nul
if errorlevel 1 (
    echo WARNING: Cannot locate python.exe
) else (
    echo SUCCESS: Python found in PATH
)
echo.

REM Test 3: pip Module
echo [TEST 3] pip Module
echo ----------------------------------------
python -m pip --version 2>nul
if errorlevel 1 (
    echo FAILED: pip module not available
    echo.
    echo SOLUTION:
    echo   Attempting to install pip...
    python -m ensurepip --default-pip
    if errorlevel 1 (
        echo   FAILED: Cannot install pip
        echo   Reinstall Python and ensure pip is included
        goto :TEST_FAILED
    ) else (
        echo   SUCCESS: pip installed
    )
) else (
    for /f "tokens=*" %%i in ('python -m pip --version 2^>^&1') do echo SUCCESS: %%i
)
echo.

REM Test 4: pip Upgrade
echo [TEST 4] pip Upgrade Test
echo ----------------------------------------
echo Attempting to upgrade pip...
python -m pip install --upgrade pip
if errorlevel 1 (
    echo FAILED: Cannot upgrade pip
    echo ERROR CODE: %ERRORLEVEL%
    echo.
    echo This may indicate:
    echo   - No internet connection
    echo   - Corporate firewall blocking PyPI
    echo   - Insufficient permissions
    echo.
) else (
    echo SUCCESS: pip upgraded successfully
)
echo.

REM Test 5: Network Connectivity
echo [TEST 5] Network Connectivity
echo ----------------------------------------
echo Testing connection to pypi.org...
ping -n 2 pypi.org >nul 2>&1
if errorlevel 1 (
    echo FAILED: Cannot reach pypi.org
    echo.
    echo Possible causes:
    echo   - No internet connection
    echo   - DNS issues
    echo   - Firewall blocking ICMP
    echo.
    echo Testing alternative connectivity...
    ping -n 2 8.8.8.8 >nul 2>&1
    if errorlevel 1 (
        echo FAILED: No internet connectivity detected
        goto :TEST_FAILED
    ) else (
        echo WARNING: Internet works but cannot reach pypi.org
        echo          May be DNS or firewall issue
    )
) else (
    echo SUCCESS: pypi.org is reachable
)
echo.

REM Test 6: PyPI Package Index Access
echo [TEST 6] PyPI Package Index Access
echo ----------------------------------------
echo Attempting to query PyPI...
python -m pip index versions pip --disable-pip-version-check >nul 2>&1
if errorlevel 1 (
    echo FAILED: Cannot access PyPI package index
    echo.
    echo This indicates:
    echo   - Corporate proxy blocking PyPI
    echo   - Firewall restrictions
    echo   - SSL/TLS certificate issues
    echo.
    echo If behind corporate proxy, configure:
    echo   set HTTP_PROXY=http://your-proxy:port
    echo   set HTTPS_PROXY=http://your-proxy:port
    echo.
) else (
    echo SUCCESS: PyPI package index accessible
)
echo.

REM Test 7: Test Package Installation
echo [TEST 7] Test Package Installation
echo ----------------------------------------
echo Installing test package: requests
python -m pip install requests --disable-pip-version-check
if errorlevel 1 (
    echo FAILED: Cannot install test package
    echo ERROR CODE: %ERRORLEVEL%
    echo.
    echo This is the actual problem preventing deployment.
    echo Check error messages above for specific cause.
    echo.
) else (
    echo SUCCESS: Test package installed successfully
    echo.
    echo Verifying import...
    python -c "import requests; print('Import successful: requests', requests.__version__)"
    if errorlevel 1 (
        echo FAILED: Package installed but cannot import
        echo This may indicate Python environment corruption
    ) else (
        echo SUCCESS: Package import works correctly
    )
)
echo.

REM Test 8: File System Permissions
echo [TEST 8] File System Permissions
echo ----------------------------------------
echo Testing write access to temp directory...
echo test > "%TEMP%\mcp_test_write.tmp" 2>nul
if errorlevel 1 (
    echo FAILED: Cannot write to temp directory
    echo.
    echo SOLUTION:
    echo   Run this script as Administrator:
    echo   Right-click deploy-mcp.bat ^> Run as administrator
    echo.
) else (
    echo SUCCESS: Write permissions OK
    del "%TEMP%\mcp_test_write.tmp" >nul 2>&1
)
echo.

REM Test 9: Python Site-Packages Location
echo [TEST 9] Python Site-Packages Location
echo ----------------------------------------
python -c "import site; print('Site packages:', site.getsitepackages()[0])" 2>nul
if errorlevel 1 (
    echo FAILED: Cannot determine site-packages location
) else (
    echo SUCCESS: Site-packages accessible
)
echo.

REM Test 10: Antivirus/Security Software Check
echo [TEST 10] Security Software Check
echo ----------------------------------------
echo Checking for common security software...
tasklist /FI "IMAGENAME eq MsMpEng.exe" 2>nul | find /i "MsMpEng.exe" >nul
if not errorlevel 1 (
    echo DETECTED: Windows Defender is running
    echo          May interfere with pip installations
    echo.
)
tasklist /FI "IMAGENAME eq avp.exe" 2>nul | find /i "avp.exe" >nul
if not errorlevel 1 (
    echo DETECTED: Kaspersky is running
    echo          May block pip installations
    echo.
)
echo If antivirus is blocking, temporarily disable and retry deployment.
echo.

REM Summary
echo ============================================================================
echo   DIAGNOSTIC SUMMARY
echo ============================================================================
echo.
echo ENVIRONMENT INFORMATION:
python --version 2>nul
python -m pip --version 2>nul
echo Current directory: %CD%
echo User: %USERNAME%
echo Computer: %COMPUTERNAME%
echo Windows version:
ver
echo.

echo NEXT STEPS:
echo.
echo If all tests passed:
echo   Run deploy-mcp.bat again
echo.
echo If tests failed:
echo   1. Review error messages above
echo   2. Fix identified issues
echo   3. Run this diagnostic again to verify
echo   4. Contact support with diagnostic output
echo.

echo MANUAL INSTALLATION FALLBACK:
echo   If automatic installation keeps failing, install packages manually:
echo.
echo   python -m pip install --upgrade pip
echo   python -m pip install google-generativeai
echo   python -m pip install rich
echo   python -m pip install mcp
echo   python -m pip install pydantic
echo   python -m pip install Flask
echo   python -m pip install requests
echo.
echo   Then run deploy-mcp.bat again
echo.
echo ============================================================================
pause
exit /b 0

:TEST_FAILED
echo.
echo ============================================================================
echo   CRITICAL TEST FAILED
echo ============================================================================
echo.
echo Cannot continue with remaining tests.
echo Fix the issue above and run diagnostics again.
echo.
echo ============================================================================
pause
exit /b 1
