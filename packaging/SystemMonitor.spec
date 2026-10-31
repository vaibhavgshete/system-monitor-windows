# PyInstaller spec: builds both release flavours from one analysis.
#   dist\SystemMonitor\SystemMonitor.exe   folder build (fast start; zipped for download)
#   dist\SystemMonitor-portable.exe        single file (download and double-click)
# Run through build.ps1, which also creates build\app.ico first.
import os
import re

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo,
    StringFileInfo,
    StringStruct,
    StringTable,
    VarFileInfo,
    VarStruct,
    VSVersionInfo,
)

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
VERSION = re.search(r'__version__ = "([^"]+)"', open(os.path.join(ROOT, "sysmon", "__init__.py")).read())[1]

# The app only uses QtCore, QtGui, QtWidgets and QtSvg.
EXCLUDE_MODULES = [
    "tkinter", "unittest", "pydoc", "ssl", "_ssl", "_hashlib", "lzma", "_lzma", "bz2", "_bz2",
    "PySide6.QtNetwork", "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtPdf", "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets", "PySide6.QtDBus", "PySide6.QtTest",
]

# Files PyInstaller's Qt hooks collect but this app never loads (matched against bundle paths).
DROP = [
    "opengl32sw.dll",  # 20 MB software OpenGL fallback; widgets don't use OpenGL
    "Qt6Quick", "Qt6Qml", "Qt6Pdf", "Qt6OpenGL", "Qt6Network", "Qt6VirtualKeyboard",
    "PySide6/translations/",  # Qt's own UI translations; the app is English-only
    "plugins/generic/", "plugins/networkinformation/", "plugins/platforminputcontexts/",
    "plugins/tls/", "plugins/styles/",  # built-in Fusion style is used
    "platforms/qdirect2d", "platforms/qminimal", "platforms/qoffscreen",
    "imageformats/qgif", "imageformats/qicns", "imageformats/qjpeg", "imageformats/qpdf",
    "imageformats/qtga", "imageformats/qtiff", "imageformats/qwbmp", "imageformats/qwebp",
]


def keep(entry) -> bool:
    dest = entry[0].replace("\\", "/")
    return not any(pattern in dest for pattern in DROP)


a = Analysis(
    [os.path.join(ROOT, "run.py")],
    pathex=[ROOT],
    datas=[(os.path.join(ROOT, "sysmon", "assets"), "sysmon/assets")],
    excludes=EXCLUDE_MODULES,
)
a.binaries = [b for b in a.binaries if keep(b)]
a.datas = [d for d in a.datas if keep(d)]
pyz = PYZ(a.pure)

nums = tuple(int(x) for x in (VERSION.split(".") + ["0", "0", "0"])[:4])
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=nums, prodvers=nums),
    kids=[
        StringFileInfo([StringTable("040904B0", [
            StringStruct("ProductName", "System Monitor"),
            StringStruct("FileDescription", "System Monitor"),
            StringStruct("CompanyName", "vaibhavgshete"),
            StringStruct("LegalCopyright", "MIT License"),
            StringStruct("FileVersion", VERSION),
            StringStruct("ProductVersion", VERSION),
            StringStruct("OriginalFilename", "SystemMonitor.exe"),
        ])]),
        VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
    ],
)
common = dict(
    console=False,
    icon=os.path.join(ROOT, "build", "app.ico"),
    version=version_info,
    upx=False,  # UPX-packed Qt DLLs trigger antivirus false positives
)

# Folder build.
exe_dir = EXE(pyz, a.scripts, [], exclude_binaries=True, name="SystemMonitor", **common)
COLLECT(exe_dir, a.binaries, a.datas, name="SystemMonitor", upx=False)

# Single-file build: everything packed into one exe that unpacks to %TEMP% at launch.
EXE(pyz, a.scripts, a.binaries, a.datas, [], name="SystemMonitor-portable", **common)
