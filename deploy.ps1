# 班务通 · 服务器一键初始化（在 Windows 服务器上以管理员身份运行一次）
#
# 用法：把 zip 解压到 C:\ 得到 C:\banwutong，然后：
#      cd C:\banwutong ; .\deploy.ps1
#
# 做完后：填 .env 两个密钥 → 运行 .\start-all.ps1

$ErrorActionPreference = 'Continue'
$root = $PSScriptRoot
Set-Location $root

function Find-Python {
    $candidates = @(
        (Join-Path $root '.venv\Scripts\python.exe'),
        "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
        "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
        "C:\Program Files\Python312\python.exe",
        "C:\Program Files\Python311\python.exe",
        "C:\Program Files\Python310\python.exe"
    )
    foreach ($path in $candidates) {
        if (Test-Path $path) { return @{ Exe = $path; Args = @() } }
    }
    try {
        $null = & py -3 --version 2>&1
        if ($LASTEXITCODE -eq 0) { return @{ Exe = 'py'; Args = @('-3') } }
    } catch { }
    try {
        $cmd = Get-Command python -ErrorAction SilentlyContinue
        if ($cmd -and $cmd.Source -notmatch 'WindowsApps') {
            return @{ Exe = $cmd.Source; Args = @() }
        }
    } catch { }
    return $null
}

Write-Host "=== 1/4 检查 Python ===" -ForegroundColor Cyan
$python = Find-Python

if (-not $python) {
    Write-Host "没有找到 Python，尝试自动安装 Python 3.12（约 2-3 分钟）..." -ForegroundColor Yellow
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        & winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements --disable-interactivity
        Write-Host "安装命令已执行，重新检测..."
        Start-Sleep -Seconds 5
        $python = Find-Python
    } else {
        Write-Host "这台服务器没有 winget，需要手动装 Python：" -ForegroundColor Red
        Write-Host "  1. 浏览器打开 https://www.python.org/downloads/ 下载 Windows 版"
        Write-Host "  2. 安装时务必勾选 Add python.exe to PATH"
        Write-Host "  3. 装完关掉这个窗口，重新开一个管理员 PowerShell，再跑一次 .\deploy.ps1"
        exit 1
    }
}

if (-not $python) {
    Write-Host "Python 仍然没装上。请手动安装后重跑本脚本。" -ForegroundColor Red
    Write-Host "  下载: https://www.python.org/downloads/（安装时勾选 Add python.exe to PATH）"
    exit 1
}

Write-Host ("使用 Python: " + $python.Exe) -ForegroundColor Green
& $python.Exe @($python.Args) --version

Write-Host "`n=== 2/4 创建虚拟环境 ===" -ForegroundColor Cyan
$venv = Join-Path $root '.venv'
$vpy = Join-Path $venv 'Scripts\python.exe'
if (-not (Test-Path $vpy)) {
    & $python.Exe @($python.Args) -m venv $venv
    if (-not (Test-Path $vpy)) {
        Write-Host "创建虚拟环境失败，请把上面的报错发出来" -ForegroundColor Red
        exit 1
    }
    Write-Host "已创建 .venv"
} else {
    Write-Host ".venv 已存在，跳过"
}

Write-Host "`n=== 3/4 安装依赖（清华镜像）===" -ForegroundColor Cyan
& $vpy -m pip install --upgrade pip --quiet --disable-pip-version-check -i https://pypi.tuna.tsinghua.edu.cn/simple
& $vpy -m pip install --disable-pip-version-check -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements.txt
& $vpy -m pip install --disable-pip-version-check -i https://pypi.tuna.tsinghua.edu.cn/simple -r requirements-bot.txt
Write-Host "依赖安装完成"

Write-Host "`n=== 4/4 准备配置文件 ===" -ForegroundColor Cyan
$envFile = Join-Path $root '.env'
if (Test-Path $envFile) {
    Write-Host ".env 已存在，不覆盖"
} else {
    Copy-Item (Join-Path $root '.env.template') $envFile
    Write-Host "已从模板生成 .env" -ForegroundColor Yellow
}

Write-Host "`n=== 初始化完成 ===" -ForegroundColor Green
Write-Host "下一步："
Write-Host "  1) notepad $envFile     补上 QQBOT_SECRET 和 BANWUTONG_LLM_API_KEY"
Write-Host "  2) cd $root ; .\start-all.ps1    启动后端和机器人"
