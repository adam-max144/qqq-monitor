# Register VXN task from XML
$taskName = "QQQ Fetch VXN Data"
$xmlPath = "C:\Users\huawei\Desktop\qqq_web\vxn_task.xml"

# Remove existing
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue

# Register from XML
$xml = Get-Content $xmlPath -Raw
Register-ScheduledTask -Xml $xml -TaskName $taskName -Force

if ($?) {
    Write-Host "SUCCESS: Task '$taskName' registered from XML"
    Write-Host ""
    Write-Host "Task runs every 30 minutes, starting 9:00 AM daily"
    Write-Host "Mon-Fri only (stops after market close)"
} else {
    Write-Host "ERROR: Registration failed"
    exit 1
}
