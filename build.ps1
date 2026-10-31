# Builds dist\SystemMonitor\SystemMonitor.exe (folder build: starts much faster than --onefile),
# trims Qt parts the app never loads, and verifies the result with --selftest.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$py = ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
    python -m venv .venv
    & $py -m pip install -r requirements.txt -r requirements-dev.txt
}

# Multi-size exe icon from sysmon\assets\logo.png.
New-Item -ItemType Directory -Force build | Out-Null
& $py tools\make_ico.py build\app.ico
if ($LASTEXITCODE -ne 0) { throw "icon generation failed" }

# The app only uses QtCore, QtGui, QtWidgets and QtSvg; everything else is dead weight.
$excludes = @(
    "tkinter", "unittest", "pydoc", "ssl", "_ssl", "_hashlib", "lzma", "_lzma", "bz2", "_bz2",
    "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtPdf", "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets", "PySide6.QtDBus", "PySide6.QtTest"
) | ForEach-Object { "--exclude-module"; $_ }

& $py -m PyInstaller --noconfirm --clean --windowed `
    --name SystemMonitor `
    --icon build\app.ico `
    --add-data "sysmon\assets;sysmon\assets" `
    @excludes `
    run.py
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

# Qt files PyInstaller's hooks collect but this app never loads.
$qt = "dist\SystemMonitor\_internal\PySide6"
$remove = @(
    "opengl32sw.dll",                     # 20 MB software OpenGL fallback (widgets don't use OpenGL)
    "Qt6Quick.dll", "Qt6Qml.dll", "Qt6QmlModels.dll", "Qt6QmlMeta.dll", "Qt6QmlWorkerScript.dll",
    "Qt6Pdf.dll", "Qt6OpenGL.dll", "Qt6Network.dll", "Qt6VirtualKeyboard.dll", "Qt6VirtualKeyboardQml.dll",
    "translations",                       # Qt's own UI translations; the app is English-only
    "plugins\generic", "plugins\networkinformation", "plugins\platforminputcontexts", "plugins\tls",
    "plugins\styles",                     # we use the built-in Fusion style
    "plugins\platforms\qdirect2d.dll", "plugins\platforms\qminimal.dll", "plugins\platforms\qoffscreen.dll",
    "plugins\imageformats\qgif.dll", "plugins\imageformats\qicns.dll", "plugins\imageformats\qjpeg.dll",
    "plugins\imageformats\qpdf.dll", "plugins\imageformats\qtga.dll", "plugins\imageformats\qtiff.dll",
    "plugins\imageformats\qwbmp.dll", "plugins\imageformats\qwebp.dll"
)
foreach ($item in $remove) {
    $path = Join-Path $qt $item
    if (Test-Path $path) { Remove-Item -Recurse -Force $path }
}

# License texts travel with the binaries (MIT for this app; LGPL notice for Qt/PySide6).
Copy-Item LICENSE, THIRD_PARTY_NOTICES.md "dist\SystemMonitor\"

# Smoke-test the trimmed build: it must start, render every tab and exit cleanly.
$check = Join-Path $env:TEMP "SystemMonitor-selftest"
if (Test-Path $check) { Remove-Item -Recurse -Force $check }
$proc = Start-Process "dist\SystemMonitor\SystemMonitor.exe" -ArgumentList "--selftest", "`"$check`"" -PassThru
if (-not $proc.WaitForExit(30000)) { Stop-Process -Id $proc.Id -Force; throw "self-test timed out" }
$shots = @(Get-ChildItem $check -Filter "selftest-*.png" -ErrorAction SilentlyContinue)
if ($proc.ExitCode -ne 0 -or $shots.Count -ne 3) { throw "self-test failed (exit $($proc.ExitCode), $($shots.Count) screenshots)" }

$size = (Get-ChildItem dist\SystemMonitor -Recurse | Measure-Object Length -Sum).Sum / 1MB
Write-Host ""
Write-Host ("Built and self-tested: {0}\dist\SystemMonitor\SystemMonitor.exe ({1:N0} MB)" -f $PSScriptRoot, $size)
Write-Host "Self-test screenshots: $check"
