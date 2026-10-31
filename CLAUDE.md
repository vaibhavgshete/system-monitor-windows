# System Monitor (Windows) — project rules

A Windows desktop replacement for Task Manager, styled after Ubuntu's GNOME System Monitor.
Reference design: `screenshots/Processes.png`, `screenshots/Resources.png`, `screenshots/Disks.png`
(GNOME's artwork: local only, git-ignored, never publish). Our own app screenshots for the README
live in `docs/images/`.
Task list and progress: `TASK.md`. Update the checkboxes there when a task is done.

## Stack
- Python 3.13, **PySide6** (Qt 6) for UI, **psutil** for system data. No other runtime dependencies
  without a good reason; this tool must stay light (target: < 80 MB RAM, < 2% CPU when idle).
- Dev tools: `pytest`, `pyinstaller` (in `requirements-dev.txt`).
- Virtual env lives in `.venv/` (not committed).

## Commands (PowerShell, from the project root)
```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt -r requirements-dev.txt
.venv\Scripts\python run.py            # run with console (debugging)
.venv\Scripts\pythonw run.py           # run without console
.venv\Scripts\python -m pytest -q      # tests (Qt runs offscreen in tests)
.\build.ps1                            # build + trim + self-test dist\SystemMonitor\SystemMonitor.exe
.venv\Scripts\python run.py --selftest DIR   # screenshot every tab into DIR, then exit
```

## Layout
```
run.py                 entry point
sysmon/
  app.py               QApplication setup, MainWindow, header bar, menu, preferences
  theme.py             light/dark palettes, Qt stylesheet, SVG icons
  sampler.py           background sampling thread -> Snapshot objects
  ntproc.py            Windows process snapshot via NtQuerySystemInformation (+ WTS user names)
  gpu.py               GPU usage/memory via PDH counters, adapter names via DXGI
  processes.py         Processes tab: model, filter proxy, view, actions
  resources.py         Resources tab: collapsible CPU / Memory / Network / Disk sections
  graph.py             HistoryGraph widget (QPainter, time-based x axis)
  filesystems.py       File Systems tab
  fmt.py               size / rate / percent formatting (pure functions)
  winutil.py           Windows-only helpers via ctypes (admin, dark title bar, ...)
  assets/logo.png      app logo (window/taskbar icon; bundled into the exe by build.ps1)
tools/make_ico.py      builds the multi-size exe icon from the logo
tests/
```

## Rules
1. **Never call psutil on the GUI thread for per-tick work.** All periodic sampling happens in
   `sampler.py` on a worker `QThread`; the UI only consumes `Snapshot` objects via signals.
   (Cheap one-off calls in response to a user action — e.g. killing a process — are fine.)
2. **Every psutil per-process call can fail** (`AccessDenied`, `NoSuchProcess`, `ZombieProcess`).
   Treat missing data as `None` and show it as italic, dimmed `N/A` — never crash, never hide the row.
3. **Models update incrementally** (insert/remove/dataChanged keyed by PID). Never reset the whole
   model on a tick — it loses selection and scroll position.
4. **Colours come from `theme.py` only.** No hard-coded colours in widgets; everything must work
   in both light and dark mode and repaint on theme change.
5. Formatting goes through `fmt.py` (decimal units like GNOME: `kB`, `MB`, `GB`, rates as `/s`).
6. Windows-specific code (ctypes, registry, shell) lives in `winutil.py` and must fail soft
   (return a sensible default) so the app still starts if a call is unavailable.
7. Destructive actions (End / Kill process) always ask for confirmation, and report
   `AccessDenied` with a hint to restart as administrator.
8. User preferences persist through `QSettings` (`HKCU\Software\SystemMonitor`).
9. Keep code plain and readable: type hints, small classes, short docstrings where the "why"
   isn't obvious. Match the style of surrounding code.
10. Before calling a task done: `pytest` passes and the app launches and renders all three tabs.
