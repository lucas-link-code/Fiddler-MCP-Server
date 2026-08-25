@echo off
setlocal enabledelayedexpansion

REM ============================================================================
REM Maintainer: build Fiddler-MCP-Bundle.zip at repo root from package/
REM Run from repo root on Windows. Requires package\CustomRules.js.
REM ============================================================================

cd /d "%~dp0"

set "PKG=%~dp0package"
set "STAGE=%TEMP%\Fiddler_MCP_pack_stage"
set "ZIP_OUT=%~dp0Fiddler-MCP-Bundle.zip"

echo ============================================================================
echo   Fiddler MCP pack-release
echo ============================================================================
echo.

if not exist "%PKG%\CustomRules.js" (
    echo ERROR: package\CustomRules.js missing. It is required in the bundle.
    exit /b 1
)

if exist "%STAGE%" rd /s /q "%STAGE%" 2>nul
mkdir "%STAGE%\Fiddler_MCP" 2>nul

set "ROOT=%STAGE%\Fiddler_MCP"

echo Copying allowlist from package\ ...
for %%F in (
    enhanced-bridge.py
    5ire-bridge.py
    gemini-fiddler-client.py
    gemini_native_tools.py
    llm_prompts.py
    llm_tool_schema.py
    pypi_tls.py
    requirements-gemini.txt
    CustomRules.js
    deploy-mcp.bat
    install-dependencies-manual.bat
    diagnose-environment.bat
    start-fiddler-mcp.bat
    README.txt
    TROUBLESHOOTING.txt
    NATIVE_TOOLS_SOAK_CHECKLIST.txt
    QUICK_START_GUIDE.txt
) do (
    if not exist "%PKG%\%%F" (
        echo ERROR: missing package\%%F
        exit /b 1
    )
    copy /y "%PKG%\%%F" "%ROOT%\%%F" >nul
)

mkdir "%ROOT%\llm_providers" 2>nul
for %%F in (
    __init__.py
    base.py
    gemini_provider.py
    deepseek_provider.py
    openrouter_provider.py
) do (
    if not exist "%PKG%\llm_providers\%%F" (
        echo ERROR: missing package\llm_providers\%%F
        exit /b 1
    )
    copy /y "%PKG%\llm_providers\%%F" "%ROOT%\llm_providers\%%F" >nul
)

if exist "%ZIP_OUT%" del /f /q "%ZIP_OUT%"

echo Creating %ZIP_OUT%...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "Compress-Archive -Path '%ROOT%\*' -DestinationPath '%ZIP_OUT%' -Force"
if errorlevel 1 (
    echo ERROR: Compress-Archive failed
    exit /b 1
)

rd /s /q "%STAGE%" 2>nul

echo.
echo [+] Built:
echo     %ZIP_OUT%
echo.
echo Ship with Fiddler-MCP-Setup.bat in the same folder.
echo.
exit /b 0
