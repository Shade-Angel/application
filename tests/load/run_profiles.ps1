param([ValidateSet('A','B')][string]$Profile = 'A')
$repoRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
Push-Location (Join-Path $repoRoot 'backend')
$locustPath = Join-Path $PSScriptRoot 'locustfile.py'
try {
if ($Profile -eq 'A') {
    $env:LOAD_PROFILE = 'A'
    $env:REQUEST_PACING_S = '0.9'
    uv run locust -f $locustPath --headless --host http://localhost:8001 --csv=load-a
} else {
    $env:LOAD_PROFILE = 'B'
    $env:REQUEST_PACING_S = '1.0'
    uv run locust -f $locustPath --headless --host http://localhost:8001 --csv=load-b
}
} finally {
    Pop-Location
}
