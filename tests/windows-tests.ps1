param(
    [ValidateSet('install', 'check', 'run')]
    [string]$Action = 'check',
    [string]$DepsDir,
    [string]$Python
)

$ErrorActionPreference = 'Stop'
$pythonArguments = @('-B')
if ($Python) {
    $pythonCommand = (Get-Command $Python -ErrorAction Stop).Source
} elseif (Get-Command py.exe -ErrorAction SilentlyContinue) {
    $pythonCommand = (Get-Command py.exe).Source
    $pythonArguments = @('-3', '-B')
} else {
    $pythonCommand = (Get-Command python.exe -ErrorAction Stop).Source
}

$pythonArguments += @((Join-Path $PSScriptRoot 'windows_test_env.py'), $Action.ToLowerInvariant())
if ($DepsDir) {
    $pythonArguments += @('--deps-dir', $DepsDir)
}
& $pythonCommand @pythonArguments
exit $LASTEXITCODE
