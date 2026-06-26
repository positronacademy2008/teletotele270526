# Power cut ke baad — local PC par WordPress post links complete karein
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "=== Positron Bot — Local Complete Setup ===" -ForegroundColor Cyan

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
}

$envText = Get-Content ".env" -Raw
if ($envText -match "your_telegram_bot_token|your_wp_username|your_wp_application_password|your_groq_key") {
    Write-Host ""
    Write-Host "IMPORTANT: .env mein abhi placeholder values hain." -ForegroundColor Yellow
    Write-Host "GitHub secrets se asli values paste karein:"
    Write-Host "  https://github.com/positronacademy2008/teletotele270526/settings/secrets/actions"
    Write-Host ""
    Write-Host "Zaroori: BOT_TOKEN, WP_USER, WP_PASS, GROQ_API_KEY"
    Write-Host ""
    notepad .env
    Read-Host "Save karke Enter dabayein"
}

Write-Host "Installing Python packages (pikepdf skip — PDF optional)..." -ForegroundColor Gray
pip install -q requests==2.31.0 beautifulsoup4==4.12.3 "openai>=1.0.0" "Pillow>=10.0.0"

Write-Host "Running diagnostics..." -ForegroundColor Gray
Get-Content ".env" | ForEach-Object {
    if ($_ -match '^\s*#' -or $_ -notmatch '=') { return }
    $name, $value = $_ -split '=', 2
    [Environment]::SetEnvironmentVariable($name.Trim(), $value.Trim().Trim('"'), "Process")
}

python diagnose.py
if ($LASTEXITCODE -ne 0) {
    Write-Host "Diagnose failed — .env values check karein." -ForegroundColor Red
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "Running WordPress catch-up (missing post links)..." -ForegroundColor Cyan
python wp_catchup.py
exit $LASTEXITCODE