$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$venvRoot = Join-Path $projectRoot ".venv"
$python = Join-Path $venvRoot "Scripts\python.exe"
$requirements = Join-Path $projectRoot "requirements.txt"
$openScript = Join-Path $projectRoot "open.vbs"
$iconPath = Join-Path $projectRoot "assets\banwutong-symbol.ico"

Write-Host "Preparing Banwutong..."

if (-not (Test-Path -LiteralPath $python)) {
  $systemPython = (Get-Command python.exe -ErrorAction SilentlyContinue).Source
  if (-not $systemPython) {
    throw "Python 3 was not found. Install Python and run this installer again."
  }
  & $systemPython -m venv $venvRoot
  if ($LASTEXITCODE -ne 0) {
    throw "Could not create the local Python environment."
  }
}

& $python -c "import fastapi, uvicorn, tzdata, pypdfium2, multipart, dotenv, rapidocr_onnxruntime" 2>$null
if ($LASTEXITCODE -ne 0) {
  & $python -m pip install --disable-pip-version-check -r $requirements
  if ($LASTEXITCODE -ne 0) {
    throw "Could not install the required packages."
  }
}

$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutChars = @([char]0x73ED, [char]0x52A1, [char]0x901A)
$shortcutName = (-join $shortcutChars) + ".lnk"
$shortcutPath = Join-Path $desktop $shortcutName
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = "$env:SystemRoot\System32\wscript.exe"
$shortcut.Arguments = '"' + $openScript + '"'
$shortcut.WorkingDirectory = $projectRoot
if (Test-Path -LiteralPath $iconPath) {
  $shortcut.IconLocation = "$iconPath,0"
} else {
  $shortcut.IconLocation = "$env:SystemRoot\System32\shell32.dll,220"
}
$shortcut.Description = "Open Banwutong"
$shortcut.Save()

Write-Host ""
Write-Host "Desktop shortcut created:"
Write-Host $shortcutPath
Write-Host ""
Write-Host "Double-click the desktop shortcut to open Banwutong."

