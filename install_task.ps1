$taskName = "QQQ Fetch VXN Data"

# Remove existing task if present
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

# Create action
$action = New-ScheduledTaskAction -Execute "python.exe" `
    -Argument "C:\Users\huawei\Desktop\qqq_web\fetch_vxn.py" `
    -WorkingDirectory "C:\Users\huawei\Desktop\qqq_web"

# Create daily trigger with 30-minute repetition
$trigger = New-ScheduledTaskTrigger -Daily -At "09:00AM"
$trigger.RepetitionInterval = [TimeSpan]::FromMinutes(30)
$trigger.RepetitionDuration = [TimeSpan]::FromDays(1)

# Settings: kill if runs over 2 min, start if missed
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 2)

# Register
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Force

if ($?) {
    Write-Host "SUCCESS: Task '$taskName' created"
    Write-Host "Runs every 30 min, starting 9:00 AM daily"
} else {
    Write-Host "ERROR: Failed to create task"
    exit 1
}
