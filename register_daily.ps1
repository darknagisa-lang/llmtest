$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$scriptPath = Join-Path $projectDir 'daily_check.bat'
if (-not (Test-Path -LiteralPath (Join-Path $projectDir '.venv\Scripts\python.exe'))) { throw 'Run run.bat first to set up the Python environment.' }
$action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument ('/c ""' + $scriptPath + '""')
$korea = [System.TimeZoneInfo]::FindSystemTimeZoneById('Korea Standard Time')
$koreaMorning = [System.TimeZoneInfo]::ConvertTime([DateTimeOffset]::UtcNow, $korea).Date.AddHours(8)
$koreaMorning = [DateTime]::SpecifyKind($koreaMorning, [DateTimeKind]::Unspecified)
$localMorning = [System.TimeZoneInfo]::ConvertTime($koreaMorning, $korea, [System.TimeZoneInfo]::Local)
$trigger = New-ScheduledTaskTrigger -Daily -At $localMorning
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable
Register-ScheduledTask -TaskName 'ProductIntelligenceDailyCheck' -Action $action -Trigger $trigger -Settings $settings -Description 'Daily YouTube review checks' -Force | Out-Null
Write-Host 'Registered daily check at 08:00 Korea time (converted to local time at registration).'
