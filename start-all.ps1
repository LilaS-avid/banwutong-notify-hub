# 启动后端 + QQ 机器人（在服务器上运行）
#   .\start-all.ps1          后台启动，日志写到 logs\
#   .\stop-all.ps1           停止
#   .\register-autostart.ps1 开机自动启动（需管理员，只需一次）

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
Set-Location $root

$vpy = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $vpy)) {
    Write-Host "找不到虚拟环境，请先运行 .\deploy.ps1" -ForegroundColor Red
    exit 1
}

$logs = Join-Path $root 'logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$pids = Join-Path $logs 'pids.txt'
Remove-Item $pids -Force -ErrorAction SilentlyContinue

Write-Host "=== 启动后端（127.0.0.1:8765）===" -ForegroundColor Cyan
$backend = Start-Process -FilePath $vpy `
    -ArgumentList '-u', '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8765' `
    -WorkingDirectory $root -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $logs 'backend.log') `
    -RedirectStandardError (Join-Path $logs 'backend.err.log')
Add-Content $pids "backend=$($backend.Id)"
Write-Host ("后端 PID: " + $backend.Id)

Start-Sleep -Seconds 6

Write-Host "=== 启动 QQ 机器人 ===" -ForegroundColor Cyan
$bot = Start-Process -FilePath $vpy `
    -ArgumentList '-u', '-m', 'scripts.run_qq_bot' `
    -WorkingDirectory $root -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput (Join-Path $logs 'bot.log') `
    -RedirectStandardError (Join-Path $logs 'bot.err.log')
Add-Content $pids "bot=$($bot.Id)"
Write-Host ("机器人 PID: " + $bot.Id)

Start-Sleep -Seconds 5
Write-Host "`n=== 状态 ===" -ForegroundColor Green
try {
    $health = Invoke-RestMethod 'http://127.0.0.1:8765/health' -TimeoutSec 5
    Write-Host ("后端: " + $health.status)
} catch {
    Write-Host "后端没起来，看 logs\backend.err.log" -ForegroundColor Red
}
Write-Host "机器人日志: logs\bot.log（出现「启动成功」即正常）"
