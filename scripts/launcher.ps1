$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$url = "http://127.0.0.1:8765/"
$healthUrl = "http://127.0.0.1:8765/health"
$venvRoot = Join-Path $projectRoot ".venv"
$python = Join-Path $venvRoot "Scripts\python.exe"
$requirements = Join-Path $projectRoot "requirements.txt"
$dataDir = Join-Path $projectRoot "data"
$stdoutLog = Join-Path $dataDir "server.log"
$stderrLog = Join-Path $dataDir "server-error.log"

function Show-LauncherError([string]$message) {
  Add-Type -AssemblyName PresentationFramework
  [System.Windows.MessageBox]::Show(
    $message,
    "Banwutong",
    [System.Windows.MessageBoxButton]::OK,
    [System.Windows.MessageBoxImage]::Error
  ) | Out-Null
}

function Test-Banwutong {
  try {
    $result = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 1
    return $result.service -eq "banwutong"
  } catch {
    return $false
  }
}

if (Test-Banwutong) {
  Start-Process -FilePath $url
  exit 0
}

if (-not (Test-Path -LiteralPath $python)) {
  Show-LauncherError "The Python environment is missing. Run install-banwutong.cmd once, then try again."
  exit 1
}

try {
  & $python -c "import fastapi, uvicorn, tzdata, pypdfium2, multipart, dotenv, rapidocr_onnxruntime" 2>$null
  if ($LASTEXITCODE -ne 0) {
    & $python -m pip install --disable-pip-version-check -r $requirements
  }
} catch {
  Show-LauncherError "Dependencies could not be installed. Run install-banwutong.cmd and check the terminal output."
  exit 1
}

New-Item -ItemType Directory -Path $dataDir -Force | Out-Null

$server = Start-Process `
  -FilePath $python `
  -ArgumentList @(
    "-m",
    "uvicorn",
    "app.main:app",
    "--host",
    "127.0.0.1",
    "--port",
    "8765"
  ) `
  -WorkingDirectory $projectRoot `
  -WindowStyle Hidden `
  -RedirectStandardOutput $stdoutLog `
  -RedirectStandardError $stderrLog `
  -PassThru

for ($attempt = 0; $attempt -lt 60; $attempt++) {
  Start-Sleep -Milliseconds 250
  if (Test-Banwutong) {
    Start-Process -FilePath $url
    exit 0
  }
  if ($server.HasExited) {
    break
  }
}

Show-LauncherError "The local service did not start. See data\server-error.log for details."
exit 1

