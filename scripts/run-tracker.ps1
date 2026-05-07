$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $projectRoot ".venv\Scripts\python.exe"
$runtimeDir = Join-Path $projectRoot "desktop_runtime"
$configPath = Join-Path $runtimeDir "tracker-config.json"
$trackerPort = if ($env:TRACKER_PORT) { [int]$env:TRACKER_PORT } else { 5000 }

if (!(Test-Path $pythonExe)) {
    throw "Python da virtualenv nao encontrado em '$pythonExe'."
}

New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null

function Get-PreferredIPv4 {
    try {
        $candidateIps = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction Stop |
            Where-Object {
                $_.IPAddress -notlike "127.*" -and
                $_.IPAddress -notlike "169.254.*" -and
                $_.PrefixOrigin -ne "WellKnown"
            } |
            Sort-Object SkipAsSource, InterfaceMetric

        if ($candidateIps) {
            return $candidateIps[0].IPAddress
        }
    }
    catch {
    }

    try {
        $addresses = [System.Net.Dns]::GetHostAddresses([System.Net.Dns]::GetHostName()) |
            Where-Object {
                $_.AddressFamily -eq [System.Net.Sockets.AddressFamily]::InterNetwork -and
                $_.IPAddressToString -notlike "127.*" -and
                $_.IPAddressToString -notlike "169.254.*"
            }

        if ($addresses) {
            return $addresses[0].IPAddressToString
        }
    }
    catch {
    }

    return "127.0.0.1"
}

$trackerHost = if ($env:TRACKER_HOST) {
    $env:TRACKER_HOST
} else {
    Get-PreferredIPv4
}

$config = [ordered]@{
    trackerHost = $trackerHost
    trackerPort = $trackerPort
    bindHost = "0.0.0.0"
    updatedAt = (Get-Date).ToString("o")
}

$config | ConvertTo-Json | Set-Content -Path $configPath -Encoding UTF8

Write-Host ""
Write-Host "Tracker pronto para a LAN"
Write-Host "Host: $trackerHost"
Write-Host "Porta: $trackerPort"
Write-Host "Config salva em: $configPath"
Write-Host ""

Push-Location $projectRoot
try {
    $env:TRACKER_BIND_HOST = "0.0.0.0"
    $env:TRACKER_HOST = $trackerHost
    $env:TRACKER_PORT = "$trackerPort"
    & $pythonExe -m src.tracker.tracker
    exit $LASTEXITCODE
}
finally {
    Pop-Location
}
