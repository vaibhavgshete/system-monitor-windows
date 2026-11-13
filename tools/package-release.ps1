# Turns the build output in dist\ into the downloadable files in build\release\:
#   SystemMonitor-<version>.exe              single file (from dist\SystemMonitor-portable.exe)
#   SystemMonitor-<version>-win64.zip        folder build (dist\SystemMonitor)
# Called by build.ps1, and by CI after the exes in dist\ have been replaced with signed copies.
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

$version = (Select-String -Path sysmon\__init__.py -Pattern '__version__ = "([^"]+)"').Matches[0].Groups[1].Value
$release = "build\release"
New-Item -ItemType Directory -Force $release | Out-Null
Get-ChildItem $release | Remove-Item -Force
Copy-Item "dist\SystemMonitor-portable.exe" "$release\SystemMonitor-v$version.exe"
Compress-Archive -Path "dist\SystemMonitor" -DestinationPath "$release\SystemMonitor-v$version-win64.zip"

Write-Host ""
Write-Host "Release files (v$version):"
Get-ChildItem $release | ForEach-Object {
    $sig = if ($_.Extension -eq ".exe") { " [" + (Get-AuthenticodeSignature $_.FullName).Status + "]" } else { "" }
    Write-Host ("  {0}  {1:N1} MB{2}" -f $_.FullName, ($_.Length / 1MB), $sig)
}
