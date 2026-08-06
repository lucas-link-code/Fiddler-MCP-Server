@echo off
setlocal enabledelayedexpansion

REM ============================================================================
REM Maintainer: build dist\Fiddler-MCP-Bundle.zip + copy Fiddler-MCP-Setup.bat
REM Run from repo root on Windows. Requires CustomRules.js on disk.
REM ============================================================================

cd /d "%~dp0"

set "DIST=%~dp0dist"
set "STAGE=%TEMP%\Fiddler_MCP_pack_stage"
set "ZIP_OUT=%DIST%\Fiddler-MCP-Bundle.zip"

echo ============================================================================
echo   Fiddler MCP pack-release
echo ============================================================================
echo.

if not exist "%~dp0CustomRules.js" (
    echo ERROR: CustomRules.js missing. It is required in the bundle.
    echo Copy the MCP-enabled CustomRules.js into the repo root before packing.
    exit /b 1
)

if exist "%STAGE%" rd /s /q "%STAGE%" 2>nul
mkdir "%STAGE%\Fiddler_MCP" 2>nul
if not exist "%DIST%" mkdir "%DIST%"

set "ROOT=%STAGE%\Fiddler_MCP"

echo Copying allowlist into stage...
for %%F in (
    enhanced-bridge.py
    5ire-bridge.py
    gemini-fiddler-client.py
    gemini_native_tools.py
    llm_prompts.py
    llm_tool_schema.py
    requirements-gemini.txt
    CustomRules.js
    deploy-mcp.bat
    install-dependencies-manual.bat
    diagnose-environment.bat
    start-fiddler-mcp.bat
    README.md
    TROUBLESHOOTING.txt
    NATIVE_TOOLS_SOAK_CHECKLIST.txt
    QUICK_START_GUIDE.txt
) do (
    if not exist "%~dp0%%F" (
        echo ERROR: missing %%F
        exit /b 1
    )
    copy /y "%~dp0%%F" "%ROOT%\%%F" >nul
)

mkdir "%ROOT%\llm_providers" 2>nul
for %%F in (
    __init__.py
    base.py
    gemini_provider.py
    deepseek_provider.py
    openrouter_provider.py
) do (
    if not exist "%~dp0llm_providers\%%F" (
        echo ERROR: missing llm_providers\%%F
        exit /b 1
    )
    copy /y "%~dp0llm_providers\%%F" "%ROOT%\llm_providers\%%F" >nul
)

if exist "%ZIP_OUT%" del /f /q "%ZIP_OUT%"

echo Creating %ZIP_OUT%...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Compress-Archive -Path '%ROOT%\*' -DestinationPath '%ZIP_OUT%' -Force"
if errorlevel 1 (
    echo ERROR: Compress-Archive failed
    exit /b 1
)

copy /y "%~dp0Fiddler-MCP-Setup.bat" "%DIST%\Fiddler-MCP-Setup.bat" >nul
if errorlevel 1 (
    echo ERROR: could not copy Fiddler-MCP-Setup.bat to dist
    exit /b 1
)

rd /s /q "%STAGE%" 2>nul

echo.
echo [+] Built:
echo     %ZIP_OUT%
echo     %DIST%\Fiddler-MCP-Setup.bat
echo.
echo Ship those two files together. End user runs Fiddler-MCP-Setup.bat.
echo.
exit /b 0
