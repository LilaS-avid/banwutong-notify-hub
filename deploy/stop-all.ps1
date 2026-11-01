# 停止后端与机器人
$root = $PSScriptRoot
$pids = Join-Path $root 'logs\pids.txt'
if (-not (Test-Path $pids)) {
    Write-Host "没有找到 pids.txt，可能没启动过"
    exit 0
}
foreach ($line in Get-Content $pids) {
    if ($line -match '^(\w+)=(\d+)$') {
        $name = $Matches[1]; $id = [int]$Matches[2]
        try {
            Stop-Process -Id $id -Force -ErrorAction Stop
            Write-Host "已停止 $name (PID $id)"
        } catch {
            Write-Host "$name (PID $id) 已不在运行"
        }
    }
}
Remove-Item $pids -Force -ErrorAction SilentlyContinue
