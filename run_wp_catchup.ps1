$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host ""
    Write-Host ".env created from .env.example"
    Write-Host "Open .env and paste these from GitHub repo secrets:"
    Write-Host "  https://github.com/positronacademy2008/teletotele270526/settings/secrets/actions"
    Write-Host "  BOT_TOKEN, WP_USER, WP_PASS, GROQ_API_KEY"
    Write-Host ""
    notepad .env
    Read-Host "After saving .env, press Enter to continue"
}

python wp_catchup.py
exit $LASTEXITCODE