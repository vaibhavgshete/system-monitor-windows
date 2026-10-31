# Builds both release flavours from packaging\SystemMonitor.spec, self-tests them, and puts the
# downloadable files in build\release\:
#   SystemMonitor-<version>.exe              single file: download and double-click
#   SystemMonitor-<version>-win64.zip        folder build: extract, starts faster
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$py = ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    python -m venv .venv
    & $py -m pip install -r requirements.txt -r requirements-dev.txt
}
$version = (Select-String -Path sysmon\__init__.py -Pattern '__version__ = "([^"]+)"').Matches[0].Groups[1].Value

# Multi-size exe icon from sysmon\assets\logo.png.
New-Item -ItemType Directory -Force build | Out-Null
& $py tools\make_ico.py build\app.ico
if ($LASTEXITCODE -ne 0) { throw "icon generation failed" }

# Unused Qt parts are filtered out inside the spec, before packing (required for the single file).
& $py -m PyInstaller --noconfirm --clean packaging\SystemMonitor.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

# License texts travel with the binaries (MIT for this app; LGPL notice for Qt/PySide6).
Copy-Item LICENSE, THIRD_PARTY_NOTICES.md "dist\SystemMonitor\"

# Smoke-test both builds: each must start, render every tab and exit cleanly.
function Test-Build([string]$exe) {
    $check = Join-Path $env:TEMP ("SystemMonitor-selftest-" + [IO.Path]::GetFileNameWithoutExtension($exe))
    if (Test-Path $check) { Remove-Item -Recurse -Force $check }
    $proc = Start-Process $exe -ArgumentList "--selftest", "`"$check`"" -PassThru
    if (-not $proc.WaitForExit(60000)) { Stop-Process -Id $proc.Id -Force; throw "self-test timed out: $exe" }
    $shots = @(Get-ChildItem $check -Filter "selftest-*.png" -ErrorAction SilentlyContinue)
    if ($proc.ExitCode -ne 0 -or $shots.Count -ne 3) { throw "self-test failed: $exe (exit $($proc.ExitCode), $($shots.Count) screenshots)" }
    Write-Host "Self-test passed: $exe (screenshots in $check)"
}
Test-Build "dist\SystemMonitor\SystemMonitor.exe"
Test-Build "dist\SystemMonitor-portable.exe"

# Release files.
$release = "build\release"
New-Item -ItemType Directory -Force $release | Out-Null
Get-ChildItem $release | Remove-Item -Force
Copy-Item "dist\SystemMonitor-portable.exe" "$release\SystemMonitor-v$version.exe"
Compress-Archive -Path "dist\SystemMonitor" -DestinationPath "$release\SystemMonitor-v$version-win64.zip"

Write-Host ""
Write-Host "Release files (v$version):"
Get-ChildItem $release | ForEach-Object { Write-Host ("  {0}  {1:N1} MB" -f $_.FullName, ($_.Length / 1MB)) }
