$ErrorActionPreference = "Stop"

$repository = "https://github.com/band-ai/band-wezterm"
$remotePackage = "band-wezterm[agents] @ git+$repository.git@main"
$scriptDirectory = $PSScriptRoot
$localProject = if ($scriptDirectory) { Join-Path $scriptDirectory "pyproject.toml" }
$isLocalProject = $localProject -and (Test-Path $localProject) -and (
    Select-String -Path $localProject -Pattern '^name = "band-wezterm"' -Quiet
)
$package = if ($isLocalProject) {
    "$scriptDirectory[agents]"
} else {
    $remotePackage
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    throw "uv is required: https://docs.astral.sh/uv/getting-started/installation/"
}

$wezTermPaths = @(
    (Join-Path $env:ProgramFiles "WezTerm"),
    (Join-Path $env:LocalAppData "Programs\\WezTerm")
)
$env:Path = ($wezTermPaths + $env:Path.Split(";")) -join ";"

& uv tool install --force --reinstall $package
& band-wezterm setup

Write-Output "Band WezTerm is installed. Run: band-wezterm"
