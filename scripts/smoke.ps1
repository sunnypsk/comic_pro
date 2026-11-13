param(
    [string]$Tag = "comicpro:smoke",
    [int]$Port = 18080,
    [switch]$SkipBuild
)

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$dataDir = Join-Path $root ".tmp-smoke-docker"
$container = "comicpro-smoke"

function Remove-Container {
    $names = @(docker ps -a --filter "name=^/$container$" --format "{{.Names}}")
    if ($names -contains $container) {
        docker rm -f $container | Out-Null
    }
}

if (-not $SkipBuild) {
    Write-Host "== docker build ==" -ForegroundColor Cyan
    docker build -t $Tag .
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

if (Test-Path $dataDir) { Remove-Item -Recurse -Force $dataDir }
New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
$mount = (Resolve-Path $dataDir).Path

Remove-Container
Write-Host "== docker run ==" -ForegroundColor Cyan
docker run -d --name $container -p "${Port}:8080" -v "${mount}:/data" -e PUID=1000 -e PGID=1000 $Tag | Out-Null
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

function Wait-Health {
    param([int]$Seconds = 90)
    $deadline = (Get-Date).AddSeconds($Seconds)
    do {
        try {
            $health = Invoke-RestMethod "http://127.0.0.1:$Port/api/health" -TimeoutSec 3
            if ($health.status -eq "ok") { return $health }
        } catch {
            Start-Sleep -Milliseconds 750
        }
    } while ((Get-Date) -lt $deadline)
    throw "container did not become healthy"
}

try {
    Write-Host "== waiting for health ==" -ForegroundColor Cyan
    $health = Wait-Health
    Write-Host ("health ok, version {0}" -f $health.version)

    $sources = Invoke-RestMethod "http://127.0.0.1:$Port/api/sources"
    $ids = @($sources.sources | ForEach-Object { $_.id })
    if ($ids -notcontains "mangapill" -or $ids -notcontains "weebcentral") {
        throw "built-in real sources are not registered: $($ids -join ', ')"
    }
    Write-Host ("sources ok: {0}" -f ($ids -join ", "))

    $search = Invoke-RestMethod "http://127.0.0.1:$Port/api/search?q=star"
    $item = $search.sources[0].items[0]
    if (-not $item) { throw "demo search returned no items" }
    $detail = Invoke-RestMethod "http://127.0.0.1:$Port/api/sources/demo/manga/$($item.key)"
    $body = @{ manga_id = $detail.id; all = $true } | ConvertTo-Json
    Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:$Port/api/downloads" -Body $body -ContentType "application/json" | Out-Null

    Write-Host "== waiting for downloads ==" -ForegroundColor Cyan
    $deadline = (Get-Date).AddSeconds(120)
    $pending = @()
    do {
        $queue = Invoke-RestMethod "http://127.0.0.1:$Port/api/downloads"
        $pending = @($queue.jobs | Where-Object { $_.status -in @("queued", "running") })
        if ($pending.Count -eq 0 -and $queue.stats.done -ge 1) { break }
        Start-Sleep -Seconds 1
    } while ((Get-Date) -lt $deadline)
    if ($pending.Count -gt 0) { throw "downloads did not finish" }

    $library = Invoke-RestMethod "http://127.0.0.1:$Port/api/library?scan=true"
    if ($library.total -lt 1) { throw "library is empty after download" }

    $files = @(Get-ChildItem -Path (Join-Path $dataDir "library") -Recurse -Filter "*.cbz")
    if ($files.Count -lt 1) { throw "no CBZ file on the host volume" }
    Write-Host ("library ok: {0} series, {1} cbz files" -f $library.total, $files.Count)

    Write-Host "== restart persistence ==" -ForegroundColor Cyan
    docker restart $container | Out-Null
    $health = Wait-Health
    $library = Invoke-RestMethod "http://127.0.0.1:$Port/api/library"
    if ($library.total -lt 1) { throw "library lost after restart" }
    Write-Host "persistence ok"

    Write-Host "SMOKE PASSED" -ForegroundColor Green
} finally {
    Remove-Container
    Remove-Item -Recurse -Force $dataDir -ErrorAction SilentlyContinue
}
