# Positron bot — local PC par chalao (WordPress + Telegram dono kaam karte hain)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".env")) {
    Write-Host "Create .env from .env.example and fill BOT_TOKEN, DEST_CHANNEL, FEED_URL, WP_* secrets."
    exit 1
}

Get-Content ".env" | ForEach-Object {
    if ($_ -match '^\s*#' -or $_ -notmatch '=') { return }
    $name, $value = $_ -split '=', 2
    [Environment]::SetEnvironmentVariable($name.Trim(), $value.Trim().Trim('"'), "Process")
}

$env:FEED_URL = if ($env:FEED_URL) { $env:FEED_URL } else { "https://tg.i-c-a.su/rss/ShikshaVibhag" }
$env:DEST_CHANNEL = if ($env:DEST_CHANNEL) { $env:DEST_CHANNEL } else { "@RAJASTHAN_TODAY" }
$env:WP_URL = if ($env:WP_URL) { $env:WP_URL } else { "https://positronacademy.in" }
$env:SKIP_WORDPRESS = "false"
$env:WP_POST_TYPE = "posts"
$env:PAGE_BUILD_MODE = "digest"

python diagnose.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

python run_bot.py