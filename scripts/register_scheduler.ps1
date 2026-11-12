# Register or update APT_WATCH_Daily_Collection in Windows Task Scheduler
$pythonExe = "C:\Users\kimwo\AppData\Local\Programs\Python\Python312\python.exe"
$scriptPath = "C:\Users\kimwo\OneDrive\문서\New project\apt-watch\scripts\daily_operation.py"
$workDir = "C:\Users\kimwo\OneDrive\문서\New project\apt-watch"

if (-not (Test-Path $pythonExe)) {
    throw "Python executable not found at $pythonExe"
}
if (-not (Test-Path $scriptPath)) {
    throw "Daily operation script not found at $scriptPath"
}

$action = New-ScheduledTaskAction -Execute $pythonExe -Argument "`"$scriptPath`"" -WorkingDirectory $workDir
$trigger = New-ScheduledTaskTrigger -Daily -At 6:00AM

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -WakeToRun `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -MultipleInstances IgnoreNew

$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask `
    -TaskName "APT_WATCH_Daily_Collection" `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "APT WATCH Daily 06:00 KST Unmanned Collection & Analytics Pipeline" `
    -Force

Write-Host "Successfully registered APT_WATCH_Daily_Collection in Windows Task Scheduler!"
