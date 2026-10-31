# Third-party software

The downloadable build of System Monitor bundles the following components.
System Monitor's own code is under the MIT license (see `LICENSE`).

| Component | License | Source |
|---|---|---|
| Qt 6 (Core, Gui, Widgets, Svg) | LGPL-3.0 | https://www.qt.io/ · https://code.qt.io/ |
| PySide6 / Shiboken6 (Qt for Python) | LGPL-3.0 | https://wiki.qt.io/Qt_for_Python |
| psutil | BSD-3-Clause | https://github.com/giampaolo/psutil |
| Python 3.13 runtime | PSF License | https://www.python.org/ |
| Microsoft Visual C++ runtime (MSVCP140 / VCRUNTIME140) | Microsoft redistributable | https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist |

## LGPL notice (Qt / PySide6)

Qt and PySide6 are used unmodified and are linked dynamically. Their libraries ship as
separate DLL/PYD files in the `_internal` folder next to `SystemMonitor.exe`, so you can replace
them with your own builds of the same version. The full LGPL-3.0 text is at
https://www.gnu.org/licenses/lgpl-3.0.html, and the corresponding source code is available
from the links above.

## Design credit

The interface is inspired by [GNOME System Monitor](https://apps.gnome.org/SystemMonitor/).
System Monitor for Windows is an independent project, not affiliated with or endorsed by GNOME,
Canonical or Microsoft. It contains no GNOME code or artwork.
