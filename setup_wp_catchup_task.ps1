# PC par har 3 minute WordPress post link catch-up (GitHub Telegram ke baad)
$ErrorActionPreference = "Stop"
$taskName = "PositronWPCatchup"
$scriptDir = $PSScriptRoot
$python = (Get-Command python).Source
$action = New-ScheduledTaskAction -Execute $python -Argument "wp_catchup.py" -WorkingDirectory $scriptDir
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 3) -RepetitionDuration ([TimeSpan]::MaxValue)
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Force
Write-Host "Scheduled task '$taskName' created. Ensure .env exists in $scriptDir"