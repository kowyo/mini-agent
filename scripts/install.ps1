$ErrorActionPreference = "Stop"

$Repo = "kowyo/mini-agent"
$ApiUrl = "https://api.github.com/repos/$Repo/releases/latest"

if (Get-Command mini -ErrorAction SilentlyContinue) {
    Write-Host "Checking for updates..."
    $Release = Invoke-RestMethod -Uri $ApiUrl
    $LATEST_VERSION = $Release.tag_name -replace '^v', ''

    $INSTALLED_VERSION = (mini --version 2>$null) -replace '^.*\s', ''
    if ($INSTALLED_VERSION -eq $LATEST_VERSION) {
        Write-Host "You're already on version " -NoNewline
        Write-Host "$INSTALLED_VERSION" -NoNewline -ForegroundColor Cyan
        Write-Host " of mini-agent (the latest version)."
        exit 0
    }
    Write-Host "Updating mini-agent from v$INSTALLED_VERSION to v$LATEST_VERSION..."
} else {
    $Release = Invoke-RestMethod -Uri $ApiUrl
}

# Check if uv is available
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "'uv' is required but not installed." -ForegroundColor Red
    $reply = Read-Host "Would you like to install uv now? [Y/n]"
    if ($reply -match "^[Yy]") {
        Write-Host "Installing uv..."
        $installScript = Invoke-RestMethod -Uri "https://astral.sh/uv/install.ps1"
        Invoke-Expression $installScript
        # Add uv to PATH for the current script session
        $uvPath = "$env:USERPROFILE\.local\bin"
        if (Test-Path "$uvPath\uv.exe") {
            $env:PATH = "$uvPath;$env:PATH"
        } elseif (Test-Path "$env:USERPROFILE\.cargo\bin\uv.exe") {
            $env:PATH = "$env:USERPROFILE\.cargo\bin;$env:PATH"
        }
        Write-Host "uv installed. Continuing with mini-agent installation..."
    } else {
        Write-Host "Aborting. Install uv manually and re-run this script."
        exit 1
    }
}

$Arch = $env:PROCESSOR_ARCHITECTURE
$ArchTag = if ($Arch -eq "ARM64") { "arm64" } else { "amd64" }

$Assets = $Release.assets | Where-Object { $_.name -like "*.whl" }

$Wheel = $Assets | Where-Object { $_.name -like "*win*$ArchTag*" } | Select-Object -First 1
if (-not $Wheel) {
    $Wheel = $Assets | Where-Object { $_.name -like "*none-any*" } | Select-Object -First 1
}

if (-not $Wheel) {
    Write-Error "No compatible wheel found for Windows/$Arch."
    exit 1
}

Write-Host "Installing mini-agent from $($Wheel.browser_download_url)..."
uv tool install --force $Wheel.browser_download_url
Write-Host "Done. Run 'mini' to get started."
