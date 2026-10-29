param(
    [string]$Server = 'https://141.144.225.42.sslip.io',
    [string]$Python = 'D:\Programs\MediaVault\.venv\Scripts\python.exe'
)
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'cache-env.ps1')
$deviceRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$deviceCache = Join-Path $deviceRoot '.codex-local'
$deviceLogs = Join-Path $deviceCache 'logs'
$deviceSecrets = Join-Path $deviceCache 'secrets'
New-Item -ItemType Directory -Force -Path $deviceLogs,$deviceSecrets | Out-Null
$deviceWorker = Join-Path $deviceRoot 'server\source_relay_worker.py'
$deviceKey = Join-Path $deviceSecrets 'source-device-ed25519.key'
$devicePidFile = Join-Path $deviceCache 'source-device.pid'
if (Test-Path -LiteralPath $devicePidFile) {
    $deviceSavedPid = [int](Get-Content -LiteralPath $devicePidFile)
    $deviceExisting = Get-CimInstance Win32_Process -Filter "ProcessId = $deviceSavedPid" -ErrorAction SilentlyContinue
    if ($deviceExisting -and $deviceExisting.CommandLine.Contains($deviceWorker)) {
        Write-Output "Source device is already running (PID $deviceSavedPid)."
        exit 0
    }
}
$deviceArguments = @('"' + $deviceWorker + '"','--server',$Server,'--key','"' + $deviceKey + '"') -join ' '
$deviceProcess = Start-Process -FilePath $Python -ArgumentList $deviceArguments -WorkingDirectory $deviceRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $deviceLogs 'source-device.stdout.log') -RedirectStandardError (Join-Path $deviceLogs 'source-device.stderr.log')
Set-Content -LiteralPath $devicePidFile -Value $deviceProcess.Id
Write-Output "Source device started (PID $($deviceProcess.Id)); no inbound port is opened."
