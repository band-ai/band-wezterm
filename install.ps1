param(
    [ValidateSet("release", "main", "source")]
    [string]$Channel = $env:BAND_WEZTERM_CHANNEL,
    [Alias("h")]
    [switch]$Help
)

$ErrorActionPreference = "Stop"

if ($Help) {
    Write-Output "Usage: install.ps1 [-Channel release|main|source] [-Help]"
    Write-Output "Installs Band WezTerm from the latest release, main, or this checkout."
    Write-Output "Defaults to source in a checkout and release otherwise."
    exit 0
}

$repository = "https://github.com/band-ai/band-wezterm"
$scriptDirectory = $PSScriptRoot
$localProject = if ($scriptDirectory) { Join-Path $scriptDirectory "pyproject.toml" }
$isLocalProject = $localProject -and (Test-Path $localProject) -and (
    Select-String -Path $localProject -Pattern '^name = "band-wezterm"' -Quiet
)

if (-not $Channel) {
    $Channel = if ($isLocalProject) { "source" } else { "release" }
}

if ($Channel -ne "source" -and -not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw "Git is required to install Band WezTerm from a release or main."
}

$package = switch ($Channel) {
    "source" {
        if (-not $isLocalProject) {
            throw "-Channel source requires a Band WezTerm checkout."
        }
        Write-Host "Installing Band WezTerm from this checkout."
        "$scriptDirectory[agents]"
    }
    "main" {
        Write-Host "Installing Band WezTerm from main."
        "band-wezterm[agents] @ git+$repository.git@main"
    }
    "release" {
        $releaseTags = & git ls-remote --refs --tags "$repository.git" "v*"
        if ($LASTEXITCODE -ne 0) {
            throw "Git access is required to find the latest Band WezTerm release."
        }
        $tag = @(
            $releaseTags |
                ForEach-Object { ($_ -split "`t")[-1].Replace("refs/tags/", "") } |
                Where-Object { $_ -match '^v\d+\.\d+\.\d+$' } |
                Sort-Object { [version]$_.Substring(1) } -Descending
        )[0]
        if (-not $tag) {
            throw "Could not determine the latest Band WezTerm release."
        }
        Write-Host "Installing Band WezTerm release $tag."
        "band-wezterm[agents] @ git+$repository.git@$tag"
    }
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
& band setup

Write-Output "Band WezTerm is installed. Run: band"
