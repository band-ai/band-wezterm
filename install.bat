@echo off
setlocal

where uv >nul 2>&1
if errorlevel 1 (
    echo uv is required: https://docs.astral.sh/uv/getting-started/installation/
    exit /b 1
)

pushd "%~dp0"
uv tool install --force --reinstall .
if errorlevel 1 (
    popd
    exit /b 1
)

band-wezterm setup
set RESULT=%ERRORLEVEL%
popd
if not "%RESULT%"=="0" exit /b %RESULT%

echo Band WezTerm is installed. Run: band-wezterm
