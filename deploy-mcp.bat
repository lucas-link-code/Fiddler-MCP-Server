@echo off
setlocal enabledelayedexpansion

REM ============================================================================
REM Fiddler MCP One-Click Deployment Script
REM ============================================================================
REM This script automates the complete setup and launch of the Gemini-powered
REM Fiddler MCP system. It handles:
REM   - Python dependency installation
REM   - Fiddler path auto-discovery
REM   - Configuration setup
REM   - CustomRules.js deployment
REM   - Service launching in separate consoles
REM ============================================================================

REM Enable diagnostic mode by setting environment variable: SET DEPLOY_DEBUG=1
REM This will show additional diagnostic information
if "%DEPLOY_DEBUG%"=="1" (
    echo [DEBUG] Diagnostic mode enabled
    echo [DEBUG] Script location: %~dp0
    echo [DEBUG] Current directory: %CD%
    echo [DEBUG] Command line args: %*
    echo.
)

REM Set script directory as working directory
cd /d "%~dp0"

REM Main execution flow
goto :MAIN

REM ============================================================================
REM MAIN ROUTINE
REM ============================================================================
:MAIN
cls
echo ============================================================================
echo   Fiddler MCP One-Click Deployment
echo ============================================================================
echo.
echo This script will:
echo   1. Check Python installation
echo   2. Find your Fiddler installation
echo   3. Install required dependencies
echo   4. Configure Gemini API settings
echo   5. Deploy CustomRules.js to Fiddler
echo   6. Launch all MCP services
echo.
echo ============================================================================
echo.

REM Step 1: Check Python
echo [1/6] Checking Python installation...
call :CHECK_PYTHON
if errorlevel 1 goto :ERROR_PYTHON_NOT_FOUND
echo [+] Python %PYTHON_VERSION% detected
echo.

REM Step 2: Find Fiddler
echo [2/6] Locating Fiddler installation...
call :FIND_FIDDLER
if errorlevel 1 goto :ERROR_FIDDLER_NOT_FOUND
echo [+] Fiddler Scripts directory: %FIDDLER_SCRIPTS_PATH%
echo.

REM Step 3: Install dependencies
echo [3/6] Installing Python dependencies...
echo    Checking if dependencies are already installed...
python -c "import google.generativeai, rich, mcp, pydantic, flask, requests" >nul 2>&1
if not errorlevel 1 (
    echo [+] All dependencies already installed, skipping installation
    echo.
    goto :SKIP_DEPS_INSTALL
)
echo    This may take a few minutes on first run...
echo.
call :PREFLIGHT_CHECK
if errorlevel 1 goto :ERROR_PREFLIGHT_FAILED
call :INSTALL_DEPS
if errorlevel 1 goto :ERROR_DEPS_FAILED
:SKIP_DEPS_INSTALL
echo [+] All dependencies ready
echo.

REM Step 4: Configuration wizard
echo [4/6] Checking configuration...
call :CONFIG_WIZARD
if errorlevel 1 goto :ERROR_CONFIG_FAILED
echo [+] Configuration ready
echo.

REM Step 5: Deploy CustomRules.js
echo [5/6] Deploying CustomRules.js to Fiddler...
call :DEPLOY_CUSTOMRULES
if errorlevel 1 goto :ERROR_DEPLOY_FAILED
echo [+] CustomRules.js deployed successfully
echo.

REM Step 6: Launch services
echo [6/6] Launching MCP services...
call :LAUNCH_SERVICES
if errorlevel 1 goto :ERROR_LAUNCH_FAILED
echo [+] All services launched
echo.

REM Display success message
echo ============================================================================
echo   DEPLOYMENT SUCCESSFUL
echo ============================================================================
echo.
echo Three console windows are now open:
echo   1. THIS WINDOW - Deployment status and instructions
echo   2. Fiddler MCP Bridge - HTTP server on port 8081
echo   3. Gemini Fiddler Client - Interactive chat interface
echo.
echo NEXT STEPS:
echo   1. In Fiddler, go to Rules ^> Reload Script (or press Ctrl+R)
echo   2. Switch to the "Gemini Fiddler Client" window
echo   3. Start analyzing your traffic with natural language queries
echo.
echo EXAMPLE QUERIES:
echo   - Show me recent sessions from the last 5 minutes
echo   - Are there any suspicious sessions?
echo   - Analyze session 123 for malicious behavior
echo   - Search for JavaScript files from example.com
echo.
echo To stop all services, close all three console windows.
echo.
echo ============================================================================
echo.
pause
exit /b 0

REM ============================================================================
REM SUBROUTINE: CHECK_PYTHON
REM Checks if Python 3.10+ is installed and accessible
REM ============================================================================
:CHECK_PYTHON
python --version >nul 2>&1
if errorlevel 1 (
    exit /b 1
)

REM Get Python version
for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYTHON_VERSION=%%i

REM Extract major and minor version
for /f "tokens=1,2 delims=." %%a in ("%PYTHON_VERSION%") do (
    set PYTHON_MAJOR=%%a
    set PYTHON_MINOR=%%b
)

REM Check if Python 3.10+
if %PYTHON_MAJOR% LSS 3 (
    exit /b 1
)
if %PYTHON_MAJOR% EQU 3 if %PYTHON_MINOR% LSS 10 (
    exit /b 1
)

exit /b 0

REM ============================================================================
REM SUBROUTINE: FIND_FIDDLER
REM Auto-discovers Fiddler Scripts directory
REM ============================================================================
:FIND_FIDDLER
set FIDDLER_SCRIPTS_PATH=

REM Check common locations in order
echo    Searching common Fiddler locations...

REM Location 1: User Documents\Fiddler2\Scripts
if exist "%USERPROFILE%\Documents\Fiddler2\Scripts\" (
    set FIDDLER_SCRIPTS_PATH=%USERPROFILE%\Documents\Fiddler2\Scripts
    echo    Found: User Documents
    exit /b 0
)

REM Location 2: User My Documents\Fiddler2\Scripts (older Windows)
if exist "%USERPROFILE%\My Documents\Fiddler2\Scripts\" (
    set FIDDLER_SCRIPTS_PATH=%USERPROFILE%\My Documents\Fiddler2\Scripts
    echo    Found: My Documents
    exit /b 0
)

REM Location 3: AppData\Fiddler2\Scripts
if exist "%APPDATA%\Fiddler2\Scripts\" (
    set FIDDLER_SCRIPTS_PATH=%APPDATA%\Fiddler2\Scripts
    echo    Found: AppData
    exit /b 0
)

REM Location 4: LocalAppData\Fiddler2\Scripts
if exist "%LOCALAPPDATA%\Fiddler2\Scripts\" (
    set FIDDLER_SCRIPTS_PATH=%LOCALAPPDATA%\Fiddler2\Scripts
    echo    Found: LocalAppData
    exit /b 0
)

REM Location 5: Try to read from registry
echo    Checking registry...
for /f "tokens=2*" %%a in ('reg query "HKCU\Software\Microsoft\Fiddler2" /v "LM.ScriptsPath" 2^>nul ^| find "ScriptsPath"') do (
    set FIDDLER_SCRIPTS_PATH=%%b
    if exist "!FIDDLER_SCRIPTS_PATH!\" (
        echo    Found: Registry
        exit /b 0
    )
)

REM Location 6: Search Program Files
echo    Searching Program Files...
for /d %%d in ("%ProgramFiles%\Fiddler*") do (
    if exist "%%d\Scripts\" (
        set FIDDLER_SCRIPTS_PATH=%%d\Scripts
        echo    Found: Program Files
        exit /b 0
    )
)

REM Location 7: Search Program Files (x86)
if exist "%ProgramFiles(x86)%" (
    for /d %%d in ("%ProgramFiles(x86)%\Fiddler*") do (
        if exist "%%d\Scripts\" (
            set FIDDLER_SCRIPTS_PATH=%%d\Scripts
            echo    Found: Program Files (x86)
            exit /b 0
        )
    )
)

REM Not found automatically - prompt user
echo.
echo    Fiddler Scripts directory not found automatically.
echo.
echo    Common locations:
echo      - %%USERPROFILE%%\Documents\Fiddler2\Scripts
echo      - %%APPDATA%%\Fiddler2\Scripts
echo      - C:\Program Files\Fiddler\Scripts
echo.
set /p FIDDLER_SCRIPTS_PATH="    Enter Fiddler Scripts path manually: "

REM Validate user input
if not exist "%FIDDLER_SCRIPTS_PATH%\" (
    echo    ERROR: Directory does not exist: %FIDDLER_SCRIPTS_PATH%
    exit /b 1
)

exit /b 0

REM ============================================================================
REM SUBROUTINE: PREFLIGHT_CHECK
REM Validates environment before attempting package installation
REM ============================================================================
:PREFLIGHT_CHECK
echo    Running pre-flight checks...

echo    [1/3] Checking pip availability...
python -m pip --version >nul 2>&1
if errorlevel 1 (
    echo    ERROR: pip module not found
    echo           Attempting to bootstrap pip...
    python -m ensurepip --default-pip
    if errorlevel 1 (
        echo    FAILED: Cannot initialize pip
        exit /b 1
    )
    echo    SUCCESS: pip initialized
)

echo    [2/3] Testing PyPI connectivity...
python -m pip search pip --disable-pip-version-check >nul 2>&1
if errorlevel 1 (
    echo    WARNING: Cannot reach PyPI using search
    echo             Attempting basic connectivity test...
    python -m pip index versions pip --disable-pip-version-check >nul 2>&1
    if errorlevel 1 (
        echo    WARNING: PyPI connectivity may be limited
        echo             Installation will be attempted anyway
        echo.
        set /p CONTINUE="    Continue? [Y/N]: "
        if /i not "!CONTINUE!"=="Y" exit /b 1
    )
)

echo    [3/3] Checking write permissions...
echo test > "%TEMP%\mcp_deploy_test.tmp" 2>nul
if errorlevel 1 (
    echo    WARNING: Limited write permissions detected
    echo             You may need to run as Administrator
    echo.
    set /p CONTINUE="    Continue? [Y/N]: "
    if /i not "!CONTINUE!"=="Y" exit /b 1
) else (
    del "%TEMP%\mcp_deploy_test.tmp" >nul 2>&1
)

echo    Pre-flight checks completed
echo.
exit /b 0

REM ============================================================================
REM SUBROUTINE: INSTALL_DEPS
REM Installs required Python packages
REM ============================================================================
:INSTALL_DEPS
echo    Testing pip availability...
python -m pip --version >nul 2>&1
if errorlevel 1 (
    echo    ERROR: pip is not available
    echo           Attempting to install pip...
    python -m ensurepip --default-pip
    if errorlevel 1 (
        echo    ERROR: Could not install pip
        echo           Please install pip manually or reinstall Python
        exit /b 1
    )
)

echo    Upgrading pip...
python -m pip install --upgrade pip
if errorlevel 1 (
    echo    WARNING: Failed to upgrade pip, continuing with current version...
)

echo.
echo    Installing Gemini dependencies...
if exist "%~dp0requirements-gemini.txt" (
    echo    Using requirements-gemini.txt
    python -m pip install -r "%~dp0requirements-gemini.txt"
    set DEPS_RESULT=!ERRORLEVEL!
) else (
    echo    Installing: google-generativeai rich
    python -m pip install google-generativeai rich
    set DEPS_RESULT=!ERRORLEVEL!
)
if !DEPS_RESULT! NEQ 0 (
    echo.
    echo    ERROR: Failed to install Gemini dependencies
    echo           Exit code: !DEPS_RESULT!
    exit /b 1
)

echo.
echo    Installing MCP dependencies...
if exist "%~dp0requirements-mcp.txt" (
    echo    Using requirements-mcp.txt
    python -m pip install -r "%~dp0requirements-mcp.txt"
    set DEPS_RESULT=!ERRORLEVEL!
) else (
    echo    Installing: mcp pydantic Flask requests
    python -m pip install mcp pydantic Flask requests
    set DEPS_RESULT=!ERRORLEVEL!
)
if !DEPS_RESULT! NEQ 0 (
    echo.
    echo    ERROR: Failed to install MCP dependencies
    echo           Exit code: !DEPS_RESULT!
    exit /b 1
)

echo.
echo    Verifying installations...
python -c "import google.generativeai; import rich; import mcp; import pydantic; import flask; import requests; print('All packages verified')"
if errorlevel 1 (
    echo    WARNING: Some packages failed to import
    echo             The system may not work correctly
    echo.
    set /p CONTINUE_ANYWAY="    Continue anyway? [Y/N]: "
    if /i not "!CONTINUE_ANYWAY!"=="Y" exit /b 1
)

exit /b 0

REM ============================================================================
REM SUBROUTINE: CONFIG_WIZARD
REM Interactive configuration setup for first-time users
REM ============================================================================
:CONFIG_WIZARD
set CONFIG_FILE=%~dp0gemini-fiddler-config.json

REM Check if config already exists
if exist "%CONFIG_FILE%" (
    echo    Using existing configuration: %CONFIG_FILE%
    exit /b 0
)

echo.
echo    ========================================================================
echo    First-Time Configuration
echo    ========================================================================
echo.
echo    You need a Gemini API key to use this system.
echo.
echo    Get your FREE API key here:
echo      https://makersuite.google.com/app/apikey
echo.
echo    (The browser will open if you press Enter without entering a key)
echo.
set /p GEMINI_API_KEY="    Enter your Gemini API key: "

REM If empty, open browser to API key page
if "!GEMINI_API_KEY!"=="" (
    echo    Opening browser to get API key...
    start https://makersuite.google.com/app/apikey
    echo.
    set /p GEMINI_API_KEY="    Enter your Gemini API key: "
)

REM Validate API key format (basic check)
if "!GEMINI_API_KEY!"=="" (
    echo    ERROR: API key is required
    exit /b 1
)

echo.
echo    Select Gemini model:
echo.
echo    RECOMMENDED (Latest and Fastest):
echo      1. gemini-2.5-flash (RECOMMENDED - Latest)
echo      2. gemini-2.0-flash
echo.
echo    POWERFUL (More capable):
echo      3. gemini-2.5-pro
echo      4. gemini-1.5-pro
echo.
echo    FAST AND EFFICIENT:
echo      5. gemini-2.5-flash-lite
echo      6. gemini-1.5-flash
echo.
set /p MODEL_CHOICE="    Select model [1]: "
if "!MODEL_CHOICE!"=="" set MODEL_CHOICE=1

REM Map choice to model name
if "!MODEL_CHOICE!"=="1" set GEMINI_MODEL=gemini-2.5-flash
if "!MODEL_CHOICE!"=="2" set GEMINI_MODEL=gemini-2.0-flash
if "!MODEL_CHOICE!"=="3" set GEMINI_MODEL=gemini-2.5-pro
if "!MODEL_CHOICE!"=="4" set GEMINI_MODEL=gemini-1.5-pro
if "!MODEL_CHOICE!"=="5" set GEMINI_MODEL=gemini-2.5-flash-lite
if "!MODEL_CHOICE!"=="6" set GEMINI_MODEL=gemini-1.5-flash

REM If invalid choice, default to gemini-2.5-flash
if "!GEMINI_MODEL!"=="" set GEMINI_MODEL=gemini-2.5-flash

echo.
set /p AUTO_SAVE="    Auto-save full response bodies to disk? [N]: "
if /i "!AUTO_SAVE!"=="Y" (
    set AUTO_SAVE_BODIES=true
) else (
    set AUTO_SAVE_BODIES=false
)

REM Create config JSON file
echo    Creating configuration file...
(
echo {
echo   "api_key": "!GEMINI_API_KEY!",
echo   "model": "!GEMINI_MODEL!",
echo   "auto_save_full_bodies": !AUTO_SAVE_BODIES!,
echo   "mcp_server_command": ["python", "5ire-bridge.py"],
echo   "bridge_url": "http://127.0.0.1:8081"
echo }
) > "%CONFIG_FILE%"

echo    Configuration saved to: %CONFIG_FILE%
echo.

exit /b 0

REM ============================================================================
REM SUBROUTINE: DEPLOY_CUSTOMRULES
REM Copies CustomRules.js to Fiddler Scripts directory
REM ============================================================================
:DEPLOY_CUSTOMRULES
set SOURCE_RULES=%~dp0CustomRules.js
set DEST_RULES=%FIDDLER_SCRIPTS_PATH%\CustomRules.js

if "%DEPLOY_DEBUG%"=="1" (
    echo [DEBUG] DEPLOY_CUSTOMRULES - Starting
    echo [DEBUG]   SOURCE_RULES: %SOURCE_RULES%
    echo [DEBUG]   DEST_RULES: %DEST_RULES%
    echo [DEBUG]   FIDDLER_SCRIPTS_PATH: %FIDDLER_SCRIPTS_PATH%
)

REM Check if source exists
if not exist "%SOURCE_RULES%" (
    echo    ERROR: CustomRules.js not found in deployment directory
    echo           Expected: %SOURCE_RULES%
    if "%DEPLOY_DEBUG%"=="1" (
        echo [DEBUG] Listing files in %~dp0:
        dir "%~dp0CustomRules*" 2>nul
    )
    exit /b 1
)

if "%DEPLOY_DEBUG%"=="1" (
    echo [DEBUG] Source file found: %SOURCE_RULES%
    echo [DEBUG] File size: 
    for %%A in ("%SOURCE_RULES%") do echo         %%~zA bytes
)

REM Backup existing CustomRules.js if present
if exist "%DEST_RULES%" (
    echo    Backing up existing CustomRules.js...
    
    REM Create a simple timestamp for backup (YYYYMMDD-HHMMSS format)
    for /f "tokens=2 delims==" %%I in ('wmic os get localdatetime /value') do set datetime=%%I
    set BACKUP_TIMESTAMP=!datetime:~0,8!-!datetime:~8,6!
    
    REM Create backup with timestamp
    copy /y "%DEST_RULES%" "%DEST_RULES%.backup.!BACKUP_TIMESTAMP!.js" >nul 2>&1
    if errorlevel 1 (
        echo    WARNING: Could not create backup ^(backup failed^), but continuing...
    ) else (
        echo    Backup created: CustomRules.js.backup.!BACKUP_TIMESTAMP!.js
    )
)

REM Copy new CustomRules.js and capture result immediately
echo    Copying CustomRules.js...

if "%DEPLOY_DEBUG%"=="1" (
    echo [DEBUG] Executing: copy /y "%SOURCE_RULES%" "%DEST_RULES%"
    copy /y "%SOURCE_RULES%" "%DEST_RULES%"
    set COPY_RESULT=%ERRORLEVEL%
    echo [DEBUG] Copy command returned: %COPY_RESULT%
) else (
    copy /y "%SOURCE_RULES%" "%DEST_RULES%" >nul 2>&1
    set COPY_RESULT=%ERRORLEVEL%
)

if "%DEPLOY_DEBUG%"=="1" (
    echo [DEBUG] COPY_RESULT=%COPY_RESULT%
    echo [DEBUG] Checking if destination file exists...
    if exist "%DEST_RULES%" (
        echo [DEBUG] Destination file EXISTS
        for %%A in ("%DEST_RULES%") do echo [DEBUG] Destination file size: %%~zA bytes
    ) else (
        echo [DEBUG] Destination file DOES NOT EXIST
    )
)

REM Check the captured copy result
if %COPY_RESULT% NEQ 0 (
    echo    ERROR: Failed to copy CustomRules.js
    echo           Source: %SOURCE_RULES%
    echo           Destination: %DEST_RULES%
    echo           Error code: %COPY_RESULT%
    echo.
    echo    Possible causes:
    echo      - Fiddler is running ^(close it and try again^)
    echo      - Insufficient permissions ^(run as Administrator^)
    echo      - File is read-only ^(check file properties^)
    echo      - Destination path is invalid
    echo.
    echo    To enable diagnostic mode, run: SET DEPLOY_DEBUG=1 before running this script
    exit /b 1
)

REM Verify the file was actually copied by checking if it exists
if not exist "%DEST_RULES%" (
    echo    ERROR: Copy command returned success ^(code 0^) but file not found at destination
    echo           This is unusual and may indicate a system issue
    echo           Destination: %DEST_RULES%
    echo.
    if "%DEPLOY_DEBUG%"=="1" (
        echo [DEBUG] Directory listing of destination folder:
        dir "%FIDDLER_SCRIPTS_PATH%" 2>nul
    )
    exit /b 1
)

echo    CustomRules.js deployed successfully
echo    Location: %DEST_RULES%

if "%DEPLOY_DEBUG%"=="1" (
    echo [DEBUG] Verification: File exists at destination
    for %%A in ("%DEST_RULES%") do echo [DEBUG] Final file size: %%~zA bytes
)

exit /b 0

REM ============================================================================
REM SUBROUTINE: LAUNCH_SERVICES
REM Launches enhanced-bridge.py and gemini-fiddler-client.py in separate windows
REM ============================================================================
:LAUNCH_SERVICES
set BRIDGE_SCRIPT=%~dp0enhanced-bridge.py
set CLIENT_SCRIPT=%~dp0gemini-fiddler-client.py

REM Check if scripts exist
if not exist "%BRIDGE_SCRIPT%" (
    echo    ERROR: enhanced-bridge.py not found
    echo           Expected: %BRIDGE_SCRIPT%
    echo           Current directory: %~dp0
    exit /b 1
)

if not exist "%CLIENT_SCRIPT%" (
    echo    ERROR: gemini-fiddler-client.py not found
    echo           Expected: %CLIENT_SCRIPT%
    echo           Current directory: %~dp0
    exit /b 1
)

REM Check if 5ire-bridge.py exists (required by client)
if not exist "%~dp05ire-bridge.py" (
    echo    ERROR: 5ire-bridge.py not found
    echo           Expected: %~dp05ire-bridge.py
    echo           This file is required by the Gemini client
    exit /b 1
)

REM Launch enhanced bridge in new window
echo    Starting Enhanced Bridge (port 8081)...
start "Fiddler MCP Bridge (Port 8081)" cmd /k "cd /d "%~dp0" && python enhanced-bridge.py"
if errorlevel 1 (
    echo    ERROR: Failed to start Enhanced Bridge
    echo           Check if cmd.exe is available
    exit /b 1
)
echo    Bridge window opened

REM Wait for bridge to start
echo    Waiting for bridge to initialize (3 seconds)...
timeout /t 3 /nobreak >nul

REM Check if bridge is responding (optional check, don't fail if curl not available)
echo    Checking bridge health...
where curl >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    curl -s --connect-timeout 2 http://127.0.0.1:8081/health >nul 2>&1
    if errorlevel 1 (
        echo    WARNING: Bridge may not have started successfully
        echo             Check the "Fiddler MCP Bridge" console window for errors
        echo             Common issue: Port 8081 already in use
        echo.
        echo    Continue anyway? Press any key or Ctrl+C to abort...
        pause >nul
    ) else (
        echo    Bridge is responding on port 8081
    )
) else (
    echo    Skipping health check (curl not available)
    echo    Check the "Fiddler MCP Bridge" window to verify it started
)

REM Launch Gemini client in new window
echo    Starting Gemini Fiddler Client...
start "Gemini Fiddler Client" cmd /k "cd /d "%~dp0" && python gemini-fiddler-client.py"
if errorlevel 1 (
    echo    ERROR: Failed to start Gemini Client
    echo           Check if cmd.exe is available
    exit /b 1
)
echo    Client window opened

REM Wait a moment for client to start
echo    Waiting for client to initialize (2 seconds)...
timeout /t 2 /nobreak >nul

exit /b 0

REM ============================================================================
REM ERROR HANDLERS
REM ============================================================================

:ERROR_PYTHON_NOT_FOUND
cls
echo ============================================================================
echo   ERROR: Python Not Found or Version Too Old
echo ============================================================================
echo.
echo This script requires Python 3.10 or later.
echo.
echo The MCP (Model Context Protocol) package requires Python 3.10+
echo and will not work with older versions.
echo.
echo Current Python version detected: %PYTHON_VERSION%
echo Required: Python 3.10 or later
echo.
echo Download Python from:
echo   https://www.python.org/downloads/
echo.
echo RECOMMENDED: Python 3.11 or 3.12
echo.
echo Installation tips:
echo   1. Download Python 3.11 or 3.12 (recommended)
echo   2. During installation, check "Add Python to PATH"
echo   3. If you have multiple Python versions, ensure 3.10+ is first in PATH
echo   4. Restart this script after installation
echo.
echo To check your Python version:
echo   python --version
echo.
echo ============================================================================
pause
exit /b 1

:ERROR_FIDDLER_NOT_FOUND
cls
echo ============================================================================
echo   ERROR: Fiddler Not Found
echo ============================================================================
echo.
echo Could not locate the Fiddler Scripts directory.
echo.
echo Please ensure:
echo   1. Fiddler is installed on this computer
echo   2. Fiddler has been run at least once (to create directories)
echo   3. The Scripts directory exists
echo.
echo If Fiddler is installed in a non-standard location, you can:
echo   - Run this script again and enter the path manually when prompted
echo   - Create the directory manually: %%USERPROFILE%%\Documents\Fiddler2\Scripts
echo.
echo ============================================================================
pause
exit /b 1

:ERROR_PREFLIGHT_FAILED
cls
echo ============================================================================
echo   ERROR: Pre-flight Check Failed
echo ============================================================================
echo.
echo The environment is not ready for package installation.
echo.
echo TROUBLESHOOTING:
echo.
echo   1. VERIFY PYTHON INSTALLATION:
echo      python --version
echo      python -m pip --version
echo.
echo   2. CHECK INTERNET CONNECTION:
echo      ping pypi.org
echo      ping 8.8.8.8
echo.
echo   3. TEST MANUAL PIP INSTALL:
echo      python -m pip install --upgrade pip
echo.
echo   4. CHECK PROXY SETTINGS:
echo      If behind corporate proxy, configure:
echo      set HTTP_PROXY=http://proxy:port
echo      set HTTPS_PROXY=http://proxy:port
echo.
echo   5. PYTHON INSTALLATION ISSUES:
echo      - If Python installed via Microsoft Store, uninstall and use python.org
echo      - Ensure "Add Python to PATH" was checked during installation
echo      - Try reinstalling Python with admin rights
echo.
echo   6. RUN AS ADMINISTRATOR:
echo      Right-click deploy-mcp.bat and select "Run as administrator"
echo.
echo ============================================================================
pause
exit /b 1

:ERROR_DEPS_FAILED
cls
echo ============================================================================
echo   ERROR: Dependency Installation Failed
echo ============================================================================
echo.
echo Failed to install required Python packages.
echo.
echo QUICK FIX OPTIONS:
echo.
echo   Option 1: Run the manual installer (RECOMMENDED)
echo   install-dependencies-manual.bat
echo.
echo   This installs each package individually with full visibility.
echo   After it completes, run deploy-mcp.bat again.
echo.
echo   Option 2: Run diagnostics to identify the issue
echo   diagnose-environment.bat
echo.
echo   This will test Python, pip, network, and permissions.
echo.
echo   Option 3: Install manually in a new Administrator command prompt
echo   python -m pip install google-generativeai rich mcp pydantic Flask requests
echo.
echo COMMON CAUSES:
echo   - No internet connection
echo   - Corporate firewall blocking PyPI
echo   - Insufficient permissions
echo   - Python from Microsoft Store (use python.org installer instead)
echo   - Antivirus blocking pip
echo.
echo For detailed troubleshooting, see TROUBLESHOOTING.txt
echo.
echo ============================================================================
pause
exit /b 1

:ERROR_CONFIG_FAILED
cls
echo ============================================================================
echo   ERROR: Configuration Failed
echo ============================================================================
echo.
echo Could not create or validate configuration.
echo.
echo Please ensure:
echo   1. You entered a valid Gemini API key
echo   2. The deployment directory is writable
echo   3. You have internet access to validate the API key
echo.
echo Get a FREE Gemini API key:
echo   https://makersuite.google.com/app/apikey
echo.
echo ============================================================================
pause
exit /b 1

:ERROR_DEPLOY_FAILED
cls
echo ============================================================================
echo   ERROR: CustomRules.js Deployment Failed
echo ============================================================================
echo.
echo Could not copy CustomRules.js to Fiddler Scripts directory.
echo.
echo Diagnostic Information:
echo   Source file: %~dp0CustomRules.js
echo   Destination: %FIDDLER_SCRIPTS_PATH%\CustomRules.js
echo   Script directory: %~dp0
echo.
echo Try these solutions:
echo   1. Close Fiddler completely and run this script again
echo   2. Run this script as Administrator (right-click ^> Run as Administrator)
echo   3. Check file permissions on the Fiddler Scripts directory
echo   4. Verify the destination path exists and is writable
echo   5. Check if antivirus is blocking the copy operation
echo   6. Manually copy CustomRules.js from:
echo      %~dp0CustomRules.js
echo      To:
echo      %FIDDLER_SCRIPTS_PATH%\CustomRules.js
echo.
echo ============================================================================
pause
exit /b 1

:ERROR_LAUNCH_FAILED
cls
echo ============================================================================
echo   ERROR: Service Launch Failed
echo ============================================================================
echo.
echo Could not start one or more services.
echo.
echo Common causes:
echo   - Port 8081 is already in use (check for other Python processes)
echo   - Python scripts are missing from the deployment directory
echo   - Python environment issues
echo.
echo To check if port 8081 is in use:
echo   netstat -ano ^| findstr :8081
echo.
echo To kill processes using port 8081:
echo   taskkill /F /PID [PID_NUMBER]
echo.
echo ============================================================================
pause
exit /b 1

