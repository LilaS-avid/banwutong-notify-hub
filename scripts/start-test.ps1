# 本地测试实例：单独端口 + 单独数据库，随便造数据，不影响正式库（8765）
#   .\scripts\start-test.ps1              启动（默认 127.0.0.1:8790，免登录）
#   .\scripts\start-test.ps1 -Stop        停止
#   .\scripts\start-test.ps1 -Port 8899   换端口
param(
    [switch]$Stop,
    [int]$Port = 8790
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    Write-Host "找不到 .venv，请先运行 .\deploy.ps1" -ForegroundColor Red
    exit 1
}

$testDir = Join-Path $root 'data-test'
$logDir = Join-Path $root 'logs'
$pidFile = Join-Path $logDir 'test.pid'
$logFile = Join-Path $logDir 'test.log'
$errFile = Join-Path $logDir 'test.err.log'

if ($Stop) {
    if (Test-Path $pidFile) {
        $old = [int](Get-Content $pidFile)
        Stop-Process -Id $old -Force -ErrorAction SilentlyContinue
        Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
        Write-Host "测试实例已停止 (PID $old)"
    } else {
        Write-Host "没有记录到正在运行的测试实例"
    }
    exit 0
}

New-Item -ItemType Directory -Force -Path $testDir, $logDir | Out-Null

# 测试实例用独立库、独立上传目录；关掉提醒循环；免登录，方便随手点
$env:BANWUTONG_DATABASE_PATH = Join-Path $testDir 'class_notice.db'
$env:BANWUTONG_UPLOAD_DIR = Join-Path $testDir 'uploads'
$env:BANWUTONG_REMINDERS_DISABLED = '1'
$env:BANWUTONG_AUTH_USER = ''
$env:BANWUTONG_AUTH_PASSWORD = ''

$proc = Start-Process -FilePath $python `
    -ArgumentList '-u', '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', "$Port" `
    -WorkingDirectory $root -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput $logFile -RedirectStandardError $errFile
Set-Content -Path $pidFile -Value $proc.Id

$ready = $false
for ($attempt = 0; $attempt -lt 40; $attempt++) {
    Start-Sleep -Milliseconds 500
    try {
        $health = Invoke-RestMethod "http://127.0.0.1:$Port/health" -TimeoutSec 2
        if ($health.status -eq 'ok') { $ready = $true; break }
    } catch { }
    if ($proc.HasExited) { break }
}

if (-not $ready) {
    Write-Host "测试实例没起来，看 logs\test.err.log" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "本地测试实例已启动（免登录，不碰正式库）" -ForegroundColor Green
Write-Host "  地址:   http://127.0.0.1:$Port/"
Write-Host "  数据:   $testDir\class_notice.db（删掉这个目录就重置）"
Write-Host "  日志:   $logFile / $errFile"
Write-Host "  停止:   .\scripts\start-test.ps1 -Stop"
Write-Host ""
Start-Process "http://127.0.0.1:$Port/"
