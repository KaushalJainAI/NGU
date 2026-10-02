# Run the NGU e2e suite. Usage: ./run.ps1 [pytest args...]
# Defaults to the local backend; override with $env:NGU_BASE_URL.
param([Parameter(ValueFromRemainingArguments = $true)] $Args)

if (-not $env:NGU_BASE_URL) { $env:NGU_BASE_URL = "http://localhost:8000" }
Write-Host "Target: $env:NGU_BASE_URL" -ForegroundColor Cyan
python -m pytest @Args
