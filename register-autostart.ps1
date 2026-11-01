# 注册开机自启（管理员运行一次）
# 服务器重启后自动拉起后端和机器人，不用人工点

$root = $PSScriptRoot
$startScript = Join-Path $root 'start-all.ps1'

if (-not (Test-Path $startScript)) {
    Write-Host "找不到 start-all.ps1" -ForegroundColor Red
    exit 1
}

$action = "powershell -NoProfile -ExecutionPolicy Bypass -File `"$startScript`""

schtasks /create /tn "Banwutong-AutoStart" /tr $action /sc onstart /ru SYSTEM /rl HIGHEST /f
if ($LASTEXITCODE -eq 0) {
    Write-Host "已注册开机自启：Banwutong-AutoStart" -ForegroundColor Green
    Write-Host "开机后会自动执行 start-all.ps1（以 SYSTEM 身份，不弹窗口）"
    Write-Host "取消自启：schtasks /delete /tn `"Banwutong-AutoStart`" /f"
} else {
    Write-Host "注册失败，请确认是以管理员身份运行" -ForegroundColor Red
}
