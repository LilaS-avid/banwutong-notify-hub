# 启动后端 + QQ 机器人（在服务器上运行）
#   .\start-all.ps1                    后台启动，日志写到 logs\；默认对局域网开放（手机可打开）
#   .\start-all.ps1 -BindAddress 127.0.0.1   只允许本机访问
#   .\stop-all.ps1                     停止
#   .\register-autostart.ps1           开机自动启动（需管理员，只需一次）
param(
    [string]$BindAddress = '0.0.0.0',
    [int]$Port = 8765
)

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

Write-Host "=== 启动后端（${BindAddress}:${Port}）===" -ForegroundColor Cyan
$backend = Start-Process -FilePath $vpy `
    -ArgumentList '-u', '-m', 'uvicorn', 'app.main:app', '--host', $BindAddress, '--port', "$Port" `
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
    $health = Invoke-RestMethod "http://127.0.0.1:$Port/health" -TimeoutSec 5
    Write-Host ("后端: " + $health.status)
} catch {
    Write-Host "后端没起来，看 logs\backend.err.log" -ForegroundColor Red
}

if ($BindAddress -eq '0.0.0.0') {
    $lanIps = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -notmatch '^(127\.|169\.254\.)' } |
        Select-Object -ExpandProperty IPAddress -Unique
    foreach ($ip in $lanIps) {
        Write-Host ""
        Write-Host "网页入口（同一局域网可开）: " -NoNewline -ForegroundColor Yellow
        Write-Host "http://${ip}:${Port}/"
        Write-Host "访客上传页（同学免登录）:   " -NoNewline -ForegroundColor Yellow
        Write-Host "http://${ip}:${Port}/?guest=1"
    }
}
Write-Host "`n机器人日志: logs\bot.log（出现「启动成功」即正常）"
