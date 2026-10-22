# Open PowerShell in the extracted oraneo folder, then run .\start-oraneo.ps1
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
if (Test-Path '.\.venv\Scripts\python.exe') {
    & '.\.venv\Scripts\python.exe' start.py
} else {
    py -3 start.py
}
exit $LASTEXITCODE
