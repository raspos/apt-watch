$task = Get-ScheduledTask -TaskName 'APT_WATCH_Daily_Collection'
$info = Get-ScheduledTaskInfo -TaskName 'APT_WATCH_Daily_Collection'
Write-Host '=== TASK GENERAL ==='
$task | Format-List TaskName, State, Author, Description
Write-Host '=== ACTIONS ==='
$task.Actions | Format-List Execute, Arguments, WorkingDirectory
Write-Host '=== TRIGGERS ==='
$task.Triggers | Format-List Enabled, StartBoundary, Repetition
Write-Host '=== SETTINGS ==='
$task.Settings | Format-List StartWhenAvailable, AllowStartIfOnBatteries, DontStopIfGoingOnBatteries, ExecutionTimeLimit, WakeToRun, MultipleInstances
Write-Host '=== TASK INFO ==='
$info | Format-List LastRunTime, LastTaskResult, NextRunTime, NumberOfMissedRuns
