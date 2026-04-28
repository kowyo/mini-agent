$ErrorActionPreference = "Stop"

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
