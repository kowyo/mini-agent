$ErrorActionPreference = "Stop"

# Check if uv is available
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "'uv' is required but not installed." -ForegroundColor Red
    $reply = Read-Host "Would you like to install uv now? [Y/n]"
    if ($reply -eq "" -or $reply -match "^[Yy]") {
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

$ApiUrl = "https://api.github.com/repos/kowyo/mini-agent/releases/latest"

$Arch = $env:PROCESSOR_ARCHITECTURE
$ArchTag = if ($Arch -eq "ARM64") { "arm64" } else { "amd64" }

$Assets = (Invoke-RestMethod -Uri $ApiUrl).assets | Where-Object { $_.name -like "*.whl" }

$Wheel = $Assets | Where-Object { $_.name -like "*win*$ArchTag*" } | Select-Object -First 1
if (-not $Wheel) {
    $Wheel = $Assets | Where-Object { $_.name -like "*none-any*" } | Select-Object -First 1
}

if (-not $Wheel) {
    Write-Error "No compatible wheel found for Windows/$Arch."
    exit 1
}

Write-Host "Installing mini-agent from $($Wheel.browser_download_url)..."
uv tool install $Wheel.browser_download_url
Write-Host "Done. Run 'mini' to get started."
