@echo off
setlocal

where uv >nul 2>&1
if errorlevel 1 (
    echo uv is required: https://docs.astral.sh/uv/getting-started/installation/
    exit /b 1
)

uv tool install --force --reinstall "%~dp0"
if errorlevel 1 exit /b 1

band-wezterm setup
if errorlevel 1 exit /b 1

echo Band WezTerm is installed. Run: band-wezterm
