param([ValidateSet('Enable','Disable','Status','Run')][string]$Action = 'Status')
$ErrorActionPreference = 'Stop'
$jmRoot = Split-Path -Parent $PSScriptRoot
$jmPython = Join-Path $jmRoot '.venv\Scripts\pythonw.exe'
$jmMonitorArgs = '-m scripts.community_monitor'
$jmMonitorName = 'JM Community Daily Monitor'
$jmExisting = Get-ScheduledTask -TaskName $jmMonitorName -ErrorAction SilentlyContinue
if ($jmExisting -and (($jmExisting.Actions.Execute -ne $jmPython) -or ($jmExisting.Actions.Arguments -ne $jmMonitorArgs) -or ($jmExisting.Actions.WorkingDirectory -ne $jmRoot))) {
    throw '同名任务不属于本工作台，未覆盖或操作。'
}
if ($Action -eq 'Enable') {
    if (-not (Test-Path -LiteralPath $jmPython)) { throw 'JM Python运行环境不存在。' }
    if ((Get-TimeZone).Id -ne 'China Standard Time') { throw '系统时区不是北京时间，请先核对每日10:30触发时间。' }
    $jmUser = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $jmAction = New-ScheduledTaskAction -Execute $jmPython -Argument $jmMonitorArgs -WorkingDirectory $jmRoot
    $jmTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 30)
    $jmPrincipal = New-ScheduledTaskPrincipal -UserId $jmUser -LogonType Interactive -RunLevel Limited
    $jmSettings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 3)
    Register-ScheduledTask -TaskName $jmMonitorName -Action $jmAction -Trigger $jmTrigger -Principal $jmPrincipal -Settings $jmSettings -Description '每30分钟只读检查JM社区任务，生成本地报告并记录状态变化；不发布、不重发、不解锁、不恢复暂停任务。电脑须开机且当前用户已登录。' -Force | Out-Null
} elseif ($Action -eq 'Disable' -and $jmExisting) {
    Disable-ScheduledTask -TaskName $jmMonitorName | Out-Null
} elseif ($Action -eq 'Run') {
    if (-not $jmExisting) { throw '请先启用每日巡检。' }
    Start-ScheduledTask -TaskName $jmMonitorName
}
$jmTask = Get-ScheduledTask -TaskName $jmMonitorName -ErrorAction SilentlyContinue
if ($jmTask) {
    $jmInfo = Get-ScheduledTaskInfo -TaskName $jmMonitorName
    [pscustomobject]@{TaskName=$jmTask.TaskName;State=[string]$jmTask.State;LastRunTime=$jmInfo.LastRunTime;NextRunTime=$jmInfo.NextRunTime;LastResult=$jmInfo.LastTaskResult;Report=(Join-Path $jmRoot 'var\community-monitor\latest.html')} | ConvertTo-Json
} else { Write-Output '每日巡检尚未注册。' }
