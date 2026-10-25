# Project-local tool caches; no global/user environment changes.
$vaultRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$vaultCache = Join-Path $vaultRoot '.codex-local'
$vaultEnvironment = @{
    TEMP = "$vaultCache\tmp"; TMP = "$vaultCache\tmp"
    npm_config_cache = "$vaultCache\cache\npm"
    PIP_CACHE_DIR = "$vaultCache\cache\pip"
    UV_CACHE_DIR = "$vaultCache\cache\uv"
    HF_HOME = "$vaultCache\cache\huggingface"
    TORCH_HOME = "$vaultCache\cache\torch"
    XDG_CACHE_HOME = "$vaultCache\cache"
    PLAYWRIGHT_BROWSERS_PATH = "$vaultCache\cache\playwright"
    PYTHONPYCACHEPREFIX = "$vaultCache\cache\pycache"
}
foreach ($vaultEntry in $vaultEnvironment.GetEnumerator()) {
    New-Item -ItemType Directory -Force -Path $vaultEntry.Value | Out-Null
    [Environment]::SetEnvironmentVariable($vaultEntry.Key, $vaultEntry.Value, 'Process')
}
