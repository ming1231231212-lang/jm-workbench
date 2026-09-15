param([int]$Port = 8776, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$jmProject = Split-Path -Parent $PSScriptRoot
$jmPython = Join-Path $jmProject '.venv\Scripts\python.exe'
$jmUrl = 'http://127.0.0.1:' + $Port
if (-not (Test-Path -LiteralPath $jmPython)) { throw '请先按README创建虚拟环境并安装依赖。' }
$jmVar = Join-Path $jmProject 'var'
New-Item -ItemType Directory -Path $jmVar -Force | Out-Null
Push-Location -LiteralPath $jmProject
try {
    $jmRevision = & $jmPython -c 'from jm_workbench.core.config import revision; print(revision())'
    $jmRunning = $false
    try {
        $jmHealth = Invoke-RestMethod -Uri ($jmUrl + '/api/health') -TimeoutSec 3
        if ($jmHealth.name -ne 'JM工作台') { throw '端口由其他应用占用。' }
        if ($jmHealth.revision -ne $jmRevision) { throw '已有JM服务加载的是旧代码，请先停止任务并重启服务。' }
        $jmRunning = $true
    } catch {
        if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) { throw }
    }
    if (-not $jmRunning) {
        Start-Process -FilePath $jmPython -ArgumentList @('-m','jm_workbench','--port',$Port) -WorkingDirectory $jmProject -WindowStyle Hidden -RedirectStandardOutput (Join-Path $jmVar 'server.stdout.log') -RedirectStandardError (Join-Path $jmVar 'server.stderr.log') | Out-Null
        for ($jmTry = 0; $jmTry -lt 20; $jmTry++) {
            Start-Sleep -Milliseconds 500
            try {
                $jmHealth = Invoke-RestMethod -Uri ($jmUrl + '/api/health') -TimeoutSec 2
                if ($jmHealth.name -eq 'JM工作台') { $jmRunning = $true; break }
            } catch { }
        }
        if (-not $jmRunning) { throw 'JM启动失败，请查看var/server.stderr.log。' }
    }
    if (-not $NoBrowser) {
        $jmPreferred = Join-Path (Split-Path -Parent $jmProject) 'Codex-Chrome\Open-CodexChrome.ps1'
        if (Test-Path -LiteralPath $jmPreferred) { & $jmPreferred -Url $jmUrl }
        else { Start-Process $jmUrl }
    }
    Write-Output $jmUrl
} finally { Pop-Location }
