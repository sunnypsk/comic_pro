param(
    [switch]$SkipDocker
)

$ErrorActionPreference = "Continue"
Set-Location (Split-Path -Parent $PSScriptRoot)

Write-Host "== ruff ==" -ForegroundColor Cyan
uv run ruff check backend
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "== pytest ==" -ForegroundColor Cyan
uv run pytest -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "== tsc ==" -ForegroundColor Cyan
pnpm -C frontend run typecheck
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "== vite build ==" -ForegroundColor Cyan
pnpm -C frontend run build
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if (-not $SkipDocker) {
    Write-Host "== docker smoke ==" -ForegroundColor Cyan
    & powershell -NoProfile -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "smoke.ps1")
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host "All checks passed." -ForegroundColor Green
