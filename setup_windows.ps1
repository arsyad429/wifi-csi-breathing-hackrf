#requires -Version 5.1
param(
    [string]$Python = "",
    [string]$HackrfBin = "",
    [switch]$RunDemo
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest
$projectRoot = $PSScriptRoot
$stamp = [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssfffffffZ")
$runId = "{0}_setup_windows_{1}" -f $stamp, ([Guid]::NewGuid().ToString("N").Substring(0,6))
$runDirectory = Join-Path (Join-Path $projectRoot "output") $runId
New-Item -ItemType Directory -Force -Path $runDirectory | Out-Null
$manifest = [ordered]@{
    status = "running"
    started_utc = [DateTime]::UtcNow.ToString("o")
    command = "setup_windows.ps1"
    python_requested = $Python
    hackrf_bin = $HackrfBin
    run_demo = [bool]$RunDemo
    powershell = $PSVersionTable.PSVersion.ToString()
    requirements_sha256 = (Get-FileHash -LiteralPath (Join-Path $projectRoot "requirements.txt") -Algorithm SHA256).Hash
    script_sha256 = (Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash
}
$manifestPath = Join-Path $runDirectory "manifest.json"
$manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
Copy-Item -LiteralPath $PSCommandPath -Destination (Join-Path $runDirectory "setup_windows.ps1")
$transcriptStarted = $false
$setupExit = 0
Push-Location -LiteralPath $projectRoot
try {
    Start-Transcript -LiteralPath (Join-Path $runDirectory "setup.log") | Out-Null
    $transcriptStarted = $true
    Write-Host "OUTPUT: $runDirectory"
    $bootstrapArgs = @()
    if ($Python) {
        $bootstrapPython = $Python
    } elseif (Get-Command py -ErrorAction SilentlyContinue) {
        $bootstrapPython = "py"
        $bootstrapArgs = @("-3")
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        $bootstrapPython = "python"
    } else {
        throw "Python tidak ditemukan. Pasang Python 3.10+ 64-bit, lalu buka PowerShell baru."
    }
    & $bootstrapPython @bootstrapArgs -c "import sys; print(sys.version); sys.exit(0 if sys.version_info >= (3,10) else 1)"
    if ($LASTEXITCODE -ne 0) { throw "Gunakan Python 3.10 atau lebih baru." }
    $venvDirectory = Join-Path $projectRoot ".venv"
    & $bootstrapPython @bootstrapArgs -m venv $venvDirectory
    if ($LASTEXITCODE -ne 0) { throw "Gagal membuat .venv." }
    $venvPython = Join-Path $venvDirectory "Scripts\python.exe"
    & $venvPython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "Gagal memperbarui pip." }
    & $venvPython -m pip install -r (Join-Path $projectRoot "requirements.txt")
    if ($LASTEXITCODE -ne 0) { throw "Instalasi requirements.txt gagal; lihat setup.log." }
    if ($HackrfBin) {
        if (-not (Test-Path -LiteralPath (Join-Path $HackrfBin "hackrf_transfer.exe"))) {
            throw "HackrfBin harus berisi hackrf_transfer.exe beserta DLL yang diperlukan."
        }
        $env:PATH = "$HackrfBin;$env:PATH"
    }
    & $venvPython (Join-Path $projectRoot "case_b.py") doctor
    if ($LASTEXITCODE -ne 0) { throw "Doctor gagal; lihat folder run doctor." }
    & $venvPython (Join-Path $projectRoot "case_b.py") selftest
    if ($LASTEXITCODE -ne 0) { throw "Selftest gagal; lihat folder run selftest." }
    if ($RunDemo) {
        & $venvPython (Join-Path $projectRoot "case_b.py") demo --seed 7
        if ($LASTEXITCODE -ne 0) { throw "Demo gagal; lihat folder run demo." }
    }
    $manifest["status"] = "completed"
    $manifest["python"] = $venvPython
    Write-Host "Selesai. Gunakan .\.venv\Scripts\python.exe case_b.py --help"
    Write-Host "Untuk capture, pastikan doctor melaporkan perangkat available."
} catch {
    $manifest["status"] = "failed"
    $manifest["error"] = $_.Exception.Message
    $_ | Out-String | Set-Content -LiteralPath (Join-Path $runDirectory "error.txt") -Encoding UTF8
    Write-Warning $_.Exception.Message
    $setupExit = 1
} finally {
    $manifest["finished_utc"] = [DateTime]::UtcNow.ToString("o")
    $manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
    if ($transcriptStarted) { Stop-Transcript | Out-Null }
    Pop-Location
}
exit $setupExit
