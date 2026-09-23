@echo off
setlocal

if /I "%~1"=="-h" goto :help
if /I "%~1"=="--help" goto :help
if /I "%~1"=="/?" goto :help
if not "%~1"=="" (
    echo Usage: install.bat
    exit /b 2
)

where uv >nul 2>&1
if errorlevel 1 (
    echo uv is required: https://docs.astral.sh/uv/getting-started/installation/
    exit /b 1
)

pushd "%~dp0"
uv tool install --force --reinstall ".[agents]"
if errorlevel 1 (
    popd
    exit /b 1
)

if exist "%ProgramFiles%\WezTerm\wezterm.exe" set "PATH=%ProgramFiles%\WezTerm;%PATH%"
if exist "%LocalAppData%\Programs\WezTerm\wezterm.exe" set "PATH=%LocalAppData%\Programs\WezTerm;%PATH%"

band setup
set RESULT=%ERRORLEVEL%
popd
if not "%RESULT%"=="0" exit /b %RESULT%

echo Band WezTerm is installed. Run: band
exit /b 0

:help
echo Usage: install.bat
echo Installs Band WezTerm from this checkout.
exit /b 0
