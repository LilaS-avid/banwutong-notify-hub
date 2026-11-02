# Keep the localhost.run tunnel alive: restarts on process exit or dead route (HTTP 502).
# Current URL is written to logs\tunnel-url.txt; events go to logs\tunnel.log.
# NOTE: PowerShell 5.1 defaults to old TLS, so force 1.2 or the HTTPS health check
# always fails and healthy tunnels get killed in a loop.

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$root = 'C:\banwutong'
$logFile = Join-Path $root 'logs\tunnel.log'
$urlFile = Join-Path $root 'logs\tunnel-url.txt'
$stopFlag = Join-Path $root 'logs\tunnel-stop.flag'
$outFile = Join-Path $env:TEMP 'bwt-tunnel-out.txt'

function Write-Log([string]$message) {
    $stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    Add-Content -Path $logFile -Value "$stamp $message" -Encoding UTF8
}

function Start-Tunnel {
    Remove-Item $outFile, "$outFile.err" -Force -ErrorAction SilentlyContinue
    $process = Start-Process -FilePath 'C:\WINDOWS\System32\OpenSSH\ssh.exe' -ArgumentList @(
        '-o', 'StrictHostKeyChecking=no',
        '-o', 'UserKnownHostsFile=NUL',
        '-o', 'ServerAliveInterval=20',
        '-o', 'ServerAliveCountMax=2',
        '-o', 'ExitOnForwardFailure=yes',
        '-R', '80:127.0.0.1:8765',
        'nokey@localhost.run'
    ) -RedirectStandardOutput $outFile -RedirectStandardError "$outFile.err" -WindowStyle Hidden -PassThru

    $url = $null
    for ($i = 0; $i -lt 15; $i++) {
        Start-Sleep -Seconds 3
        if (Test-Path $outFile) {
            $match = Select-String -Path $outFile -Pattern 'https://[a-z0-9]+\.lhr\.life' -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($match) { $url = $match.Matches[0].Value; break }
        }
    }
    if ($url) {
        Set-Content -Path $urlFile -Value $url -Encoding UTF8
        Write-Log "new url $url"
    } else {
        Write-Log 'tunnel url not found'
    }
    return [pscustomobject]@{ Process = $process; Url = $url }
}

function Test-Route([string]$url) {
    for ($attempt = 1; $attempt -le 2; $attempt++) {
        try {
            $response = Invoke-WebRequest -Uri ($url + '/health') -UseBasicParsing -TimeoutSec 20
            if ($response.StatusCode -eq 200) { return $true }
        } catch {
            # one retry before declaring the route dead
        }
        Start-Sleep -Seconds 5
    }
    return $false
}

Write-Log 'supervisor started'
while ($true) {
    if (Test-Path $stopFlag) { Write-Log 'stop flag found, exiting'; break }
    $tunnel = Start-Tunnel
    while ($true) {
        Start-Sleep -Seconds 60
        if (Test-Path $stopFlag) { Write-Log 'stop flag found, exiting'; break }
        if ($tunnel.Process.HasExited) {
            Write-Log 'ssh exited, reconnecting'
            break
        }
        if (-not $tunnel.Url) {
            Stop-Process -Id $tunnel.Process.Id -Force -ErrorAction SilentlyContinue
            break
        }
        if (-not (Test-Route $tunnel.Url)) {
            Write-Log "route dead $($tunnel.Url), restarting"
            Stop-Process -Id $tunnel.Process.Id -Force -ErrorAction SilentlyContinue
            break
        }
    }
    Start-Sleep -Seconds 5
}
