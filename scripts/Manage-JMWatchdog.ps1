param([ValidateSet('Enable','Disable','Status')][string]$Action = 'Status')
$ErrorActionPreference = 'Stop'
$jmRoot = Split-Path -Parent $PSScriptRoot
$jmPython = Join-Path $jmRoot '.venv\Scripts\python.exe'
$jmPythonWindowless = Join-Path $jmRoot '.venv\Scripts\pythonw.exe'
$jmConfig = Join-Path $jmRoot 'var\service-watchdog.json'
$jmDisabled = Join-Path $jmRoot 'var\service-watchdog.disabled'
$jmState = Join-Path $jmRoot 'var\service-watchdog-state.json'
$jmTaskName = 'JM Workbench Watchdog'

if ($Action -eq 'Enable') {
    if (-not (Test-Path -LiteralPath $jmPythonWindowless)) { throw 'Python无窗口启动程序不存在。' }
    Push-Location -LiteralPath $jmRoot
    try {
        & $jmPython -m scripts.service_watchdog --config $jmConfig --configure
        if ($LASTEXITCODE -ne 0) { throw '守护配置验证失败，未安装计划任务。' }
    } finally { Pop-Location }
    $jmUser = [Security.Principal.WindowsIdentity]::GetCurrent().Name
    $jmArgs = '-m scripts.service_watchdog --config "{0}"' -f $jmConfig
    $jmExisting = Get-ScheduledTask -TaskName $jmTaskName -ErrorAction SilentlyContinue
    if ($jmExisting -and (($jmExisting.Actions.Execute -ne $jmPythonWindowless) -or ($jmExisting.Actions.Arguments -ne $jmArgs))) {
        throw '同名计划任务不是本工作台守护入口，未覆盖。'
    }
    $jmTaskAction = New-ScheduledTaskAction -Execute $jmPythonWindowless -Argument $jmArgs -WorkingDirectory $jmRoot
    $jmTriggers = @(
        (New-ScheduledTaskTrigger -AtLogOn -User $jmUser),
        (New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 1))
    )
    $jmPrincipal = New-ScheduledTaskPrincipal -UserId $jmUser -LogonType Interactive -RunLevel Limited
    $jmSettings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
    Register-ScheduledTask -TaskName $jmTaskName -Action $jmTaskAction -Trigger $jmTriggers -Principal $jmPrincipal -Settings $jmSettings -Description 'JM后台守护：每30秒检查，只恢复服务，不重新启动暂停的业务任务或解除风险。' -Force | Out-Null
    if (Test-Path -LiteralPath $jmDisabled) { Remove-Item -LiteralPath $jmDisabled }
    Start-ScheduledTask -TaskName $jmTaskName
} elseif ($Action -eq 'Disable') {
    Set-Content -LiteralPath $jmDisabled -Value 'Disabled by user' -Encoding UTF8
    $jmExisting = Get-ScheduledTask -TaskName $jmTaskName -ErrorAction SilentlyContinue
    if ($jmExisting) { Disable-ScheduledTask -TaskName $jmTaskName | Out-Null }
    Write-Output '自动恢复已暂停；不会停止正在运行的工作台或修改业务任务。'
}

$jmTask = Get-ScheduledTask -TaskName $jmTaskName -ErrorAction SilentlyContinue
if ($jmTask) {
    $jmInfo = Get-ScheduledTaskInfo -TaskName $jmTaskName
    [pscustomobject]@{ TaskName=$jmTask.TaskName; State=[string]$jmTask.State; LastRunTime=$jmInfo.LastRunTime; LastResult=$jmInfo.LastTaskResult; Paused=(Test-Path -LiteralPath $jmDisabled) } | Format-List
} else { Write-Output '尚未注册自动恢复计划任务。' }
if (Test-Path -LiteralPath $jmState) { Get-Content -LiteralPath $jmState -Encoding UTF8 }
