@echo off
setlocal enabledelayedexpansion

REM ============================================================================
REM Fiddler MCP two-file outer setup
REM Place next to Fiddler-MCP-Bundle.zip and double-click.
REM Extracts to %USERPROFILE%\Fiddler_MCP then runs deploy-mcp.bat.
REM Parentheses in the script folder (Chrome " (2)" downloads) must not sit
REM inside cmd IF (...) blocks; those are parsed as grouping operators.
REM ============================================================================

set "SETUP_DIR=%~dp0"
set "BUNDLE_ZIP=%SETUP_DIR%Fiddler-MCP-Bundle.zip"
set "INSTALL_DIR=%USERPROFILE%\Fiddler_MCP"
set "EXTRACT_DIR=%TEMP%\Fiddler_MCP_extract"
set "DEPLOY_FROM_SETUP=1"

cls
echo ============================================================================
echo   Fiddler MCP Setup
echo ============================================================================
echo.
echo Bundle:  "%BUNDLE_ZIP%"
echo Install: "%INSTALL_DIR%"
echo.
echo This will extract the package, install dependencies, deploy CustomRules.js,
echo and start the bridge + client. API keys are entered in the client window.
echo.

if not exist "%BUNDLE_ZIP%" goto :ERR_NO_BUNDLE

if exist "%INSTALL_DIR%\gemini-fiddler-config.json" goto :PROMPT_REFRESH
if exist "%INSTALL_DIR%" goto :PROMPT_NONEMPTY
goto :PREP

:PROMPT_REFRESH
echo Existing install found. Config will be backed up before refresh.
set /p OVERWRITE="Refresh runtime files in %INSTALL_DIR%? [Y/N]: "
if /i not "!OVERWRITE!"=="Y" goto :CANCELLED
goto :PREP

:PROMPT_NONEMPTY
dir /b "%INSTALL_DIR%" >nul 2>&1
if errorlevel 1 goto :PREP
set /p OVERWRITE="Install folder exists. Overwrite runtime files? [Y/N]: "
if /i not "!OVERWRITE!"=="Y" goto :CANCELLED
goto :PREP

:CANCELLED
echo Cancelled.
pause
exit /b 1

:PREP
echo.
echo [1/4] Preparing extract folder...
if exist "%EXTRACT_DIR%" rd /s /q "%EXTRACT_DIR%" 2>nul
mkdir "%EXTRACT_DIR%" 2>nul
if not exist "%INSTALL_DIR%" mkdir "%INSTALL_DIR%"

if not exist "%INSTALL_DIR%\gemini-fiddler-config.json" goto :EXTRACT
echo       Backing up gemini-fiddler-config.json
copy /y "%INSTALL_DIR%\gemini-fiddler-config.json" "%INSTALL_DIR%\gemini-fiddler-config.json.bak" >nul

:EXTRACT
echo [2/4] Extracting bundle...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Expand-Archive -LiteralPath '%BUNDLE_ZIP%' -DestinationPath '%EXTRACT_DIR%' -Force"
if errorlevel 1 goto :ERR_EXTRACT

REM Prefer flat contents; also accept a single top-level Fiddler_MCP folder
set "SRC_ROOT=%EXTRACT_DIR%"
if exist "%EXTRACT_DIR%\Fiddler_MCP\deploy-mcp.bat" set "SRC_ROOT=%EXTRACT_DIR%\Fiddler_MCP"
if exist "%EXTRACT_DIR%\deploy-mcp.bat" set "SRC_ROOT=%EXTRACT_DIR%"

if not exist "%SRC_ROOT%\deploy-mcp.bat" goto :ERR_NO_DEPLOY

echo [3/4] Copying into %INSTALL_DIR%...
robocopy "%SRC_ROOT%" "%INSTALL_DIR%" /E /NFL /NDL /NJH /NJS /nc /ns /np >nul
set "RC=!ERRORLEVEL!"
if !RC! GEQ 8 goto :ERR_ROBOCOPY

echo [4/4] Running inner deploy...
echo.
cd /d "%INSTALL_DIR%"
call "%INSTALL_DIR%\deploy-mcp.bat"
set "DEPLOY_RC=!ERRORLEVEL!"

echo.
echo ============================================================================
echo Install folder: %INSTALL_DIR%
echo Re-start later:  %INSTALL_DIR%\start-fiddler-mcp.bat
echo Full re-deploy:  %INSTALL_DIR%\deploy-mcp.bat
echo ============================================================================
echo.
pause
exit /b !DEPLOY_RC!

:ERR_NO_BUNDLE
echo ERROR: Fiddler-MCP-Bundle.zip not found next to this script.
echo Expected: "%BUNDLE_ZIP%"
echo.
pause
exit /b 1

:ERR_EXTRACT
echo ERROR: Failed to extract zip. Need PowerShell Expand-Archive on Windows 10+.
pause
exit /b 1

:ERR_NO_DEPLOY
echo ERROR: deploy-mcp.bat missing after extract.
echo Checked: "%EXTRACT_DIR%"
pause
exit /b 1

:ERR_ROBOCOPY
echo ERROR: robocopy failed with code !RC!
pause
exit /b 1
