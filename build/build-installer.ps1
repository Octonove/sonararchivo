# Genera el instalador de SonarArchivo con Inno Setup. Reconstruye el dist por
# defecto; -SkipBuild lo reutiliza. Version = APP_VERSION (fuente unica).
param([switch]$SkipBuild)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$distExe = Join-Path $root "dist\SonarArchivo\SonarArchivo.exe"

if ($SkipBuild -and (Test-Path $distExe)) {
    Write-Host "Reutilizando dist (-SkipBuild)." -ForegroundColor DarkGray
    # el .iss exige build/icon.ico (lo genera build.ps1): regenerarlo si falta
    if (-not (Test-Path (Join-Path $PSScriptRoot "icon.ico"))) {
        $py = Join-Path $root "..\CapturaPro\.venv\Scripts\python.exe"
        if (-not (Test-Path $py)) { $py = "python" }
        & $py (Join-Path $PSScriptRoot "gen_icon.py")
    }
} else {
    & (Join-Path $PSScriptRoot "build.ps1")
    if ($LASTEXITCODE -ne 0) { Write-Host "Fallo el build." -ForegroundColor Red; exit 1 }
}
if (-not (Test-Path $distExe)) { Write-Host "No existe el dist; abortando." -ForegroundColor Red; exit 1 }

$initPy = Join-Path $root "sonararchivo\__init__.py"
$m = Select-String -Path $initPy -Pattern 'APP_VERSION\s*=\s*"([^"]+)"'
if (-not $m) { Write-Host "ERROR: no se encontro APP_VERSION." -ForegroundColor Red; exit 1 }
$ver = $m.Matches[0].Groups[1].Value
Write-Host "Version: $ver" -ForegroundColor Green

$iscc = (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source
if (-not $iscc) {
    foreach ($p in @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
                     "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
                     "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe")) {
        if (Test-Path $p) { $iscc = $p; break }
    }
}
if (-not $iscc) {
    Write-Host "No se encontro Inno Setup (ISCC.exe). winget install JRSoftware.InnoSetup" -ForegroundColor Red
    exit 1
}
# Se compila a una carpeta TEMPORAL (via /O, que pisa el OutputDir del .iss)
# porque el Windows Search Indexer bloquea intermitentemente la carpeta de
# salida bajo el perfil e Inno falla con "EndUpdateResource failed (110)".
# Luego se mueve a installer\. (Mismo arreglo que CapturaPro/CapturaStudio/GuiaClick.)
$tmpOut = Join-Path $env:TEMP "SonarArchivo_setup_build"
New-Item -ItemType Directory -Force -Path $tmpOut | Out-Null
& $iscc "/O$tmpOut" "/DMyAppVersion=$ver" (Join-Path $PSScriptRoot "SonarArchivo.iss")
if ($LASTEXITCODE -eq 0) {
    $built = Get-ChildItem (Join-Path $tmpOut "SonarArchivo-Setup-*.exe") -ErrorAction SilentlyContinue |
             Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $built) {
        Write-Host "No se encontro el instalador compilado en $tmpOut." -ForegroundColor Red
        exit 1
    }
    New-Item -ItemType Directory -Force -Path (Join-Path $root "installer") | Out-Null
    $dest = Join-Path $root ("installer\" + $built.Name)
    Move-Item -Force -Path $built.FullName -Destination $dest
    Write-Host "`nInstalador: $dest" -ForegroundColor Green
} else {
    Write-Host "Fallo el instalador (codigo $LASTEXITCODE)." -ForegroundColor Red
    exit $LASTEXITCODE
}
