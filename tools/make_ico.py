"""Write a multi-resolution .ico from sysmon/assets/logo.png (used by build.ps1 for the exe icon).

Qt's ICO writer stores a single image; Explorer and the taskbar look sharper with one image per
size, so this writes the ICO container by hand with PNG-compressed entries (Windows Vista+).
"""

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QGuiApplication, QImage

ROOT = Path(__file__).resolve().parent.parent
SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def main(out: str) -> None:
    QGuiApplication([])
    logo = QImage(str(ROOT / "sysmon" / "assets" / "logo.png"))
    if logo.isNull():
        raise SystemExit("logo.png not found")

    images = []
    for size in SIZES:
        scaled = logo.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        data = QByteArray()
        buf = QBuffer(data)
        buf.open(QIODevice.OpenModeFlag.WriteOnly)
        scaled.save(buf, "PNG")
        images.append((size, bytes(data)))

    header = struct.pack("<HHH", 0, 1, len(images))  # reserved, type 1 = icon, count
    offset = len(header) + 16 * len(images)
    entries, blobs = b"", b""
    for size, png in images:
        dim = 0 if size >= 256 else size  # 0 means 256 in the ICO format
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset)
        blobs += png
        offset += len(png)
    Path(out).write_bytes(header + entries + blobs)
    print(f"wrote {out} ({len(images)} sizes)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "build/app.ico")
