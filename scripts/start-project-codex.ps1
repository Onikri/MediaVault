param([Parameter(ValueFromRemainingArguments = $true)][string[]]$CodexArguments)
. "$PSScriptRoot\cache-env.ps1"
# CODEX_HOME is read when Codex starts. It cannot relocate an already running app.
[Environment]::SetEnvironmentVariable('CODEX_HOME', "$vaultCache\home", 'Process')
Set-Location -LiteralPath $vaultRoot
& codex @CodexArguments
exit $LASTEXITCODE
