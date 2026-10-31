# TASK.md — System Monitor for Windows

Goal: a clean, readable Task Manager replacement that looks and behaves like Ubuntu's
GNOME System Monitor (see `screenshots/`). Rules live in `CLAUDE.md`.

Legend: `[x]` done · `[ ]` to do · `[~]` partial

## Phase 0 — Project setup
- [x] `requirements.txt` (PySide6, psutil) and `requirements-dev.txt` (pytest, pyinstaller)
- [x] `.venv` created, dependencies installed
- [x] `run.py` entry point and `sysmon/` package skeleton
- [x] `.gitignore`

## Phase 1 — Core plumbing
- [x] `fmt.py`: sizes (`127.5 MB`), rates (`413.3 kB/s`), percentages, durations
- [x] `sampler.py`: worker thread sampling every N ms (default 1 s), emits `Snapshot`
  - [x] Per-process: name, user, % CPU (divided by core count), memory, disk read/write totals and rates, priority, exe path
  - [x] System: per-core CPU, memory, swap (page file), network rx/tx, disk read/write
  - [x] Caches for slow lookups (user name, exe path) keyed by PID, with a time budget per tick
  - [x] Interval change and clean shutdown
- [x] `ntproc.py`: whole-system process snapshot via `NtQuerySystemInformation` (about 10 ms per tick
      instead of about 500 ms with psutil; no AccessDenied gaps for CPU, memory or I/O), plus user
      names via `WTSEnumerateProcessesEx`
- [x] `theme.py`: Adwaita-like light and dark palettes, global stylesheet, SVG icons tinted per theme
- [x] Follow the Windows light/dark setting ("System" mode) and switch live
- [x] `winutil.py`: is-admin check, restart as admin, dark title bar, taskbar app id, volume labels

## Phase 2 — Main window
- [x] Header bar with centred Processes / Resources / File Systems switcher (icon + label)
- [x] Search button (Processes tab only) and hamburger menu on the right
- [x] Remember window size/position and last tab

## Phase 3 — Processes tab
- [x] Table: Process Name (with app icon), User, % CPU, ID, Memory, Disk read total, Disk write total, Disk read, Disk write, Priority
- [x] Incremental model updates (selection and scroll survive refreshes)
- [x] Sort by any column (numeric sort on raw values); default sort by % CPU descending
- [x] Show/hide and reorder columns from the header (persisted); User hidden by default
- [x] Search bar (Ctrl+F, or type-to-search; Esc to close), filters by name or PID
- [x] View filter: All / My / Active processes (hamburger menu, persisted)
- [x] "End Process" button + Delete key, with confirmation; multi-select supported
- [x] Right-click menu: End Process, End Process Tree, Change Priority, Open File Location, Copy name/ID, Properties
- [x] Access-denied message with a "Restart as Administrator" button
- [x] Process properties dialog (path, command line, start time, threads, handles, ...)
- [x] Tree view ("Show Dependencies" in the menu, persisted): incremental tree model, PID-reuse safe,
      branches stay expanded except ones you collapse; search keeps the ancestors of matches
- [ ] User names for other users' processes when not elevated (Windows only reveals them to admins)

## Phase 4 — Resources tab
- [x] `HistoryGraph` widget: 60 s time-based window, grid, right-side Y labels, bottom time labels, smoothed curves
- [x] Collapsible sections with remembered state
- [x] CPU: stacked per-core area graph + legend grid (colour swatch, CPUn, %), total % in header
- [x] Memory and Swap: two lines + donut legend (used / total / %)
- [x] Network: receiving / sending lines, auto-scaled axis, current rate + totals
- [x] Disk: read / write lines, auto-scaled axis, current rate + totals
- [x] GPU: one line per adapter (PDH "GPU Engine" counters, busiest engine like Task Manager),
      GPU memory graph (dedicated + shared in use) with dedicated/shared breakdown and limits, adapter names via DXGI; optional "% GPU" process column (hidden by default)
- [ ] Click a colour swatch to change a graph colour (as in GNOME)

## Phase 5 — File Systems tab
- [x] Table: Device (drive icon + label), Directory, Type, Total, Available, Used, usage bar with %
- [x] Refresh every 5 s on the worker thread; skip drives that aren't ready (empty card readers, DVD)
- [x] Double-click opens the drive in Explorer
- [x] Bar turns red at 90% full

## Phase 6 — Preferences and polish
- [x] Preferences dialog: update interval, appearance (System / Light / Dark), divide CPU by core count (all live)
- [x] "Restart as Administrator" menu item (hidden when already elevated; title shows "(Administrator)")
- [x] Keyboard shortcuts: Ctrl+1/2/3 tabs, Ctrl+F search, Delete end process, Ctrl+, preferences, Ctrl+Q quit
- [x] About dialog

## Phase 7 — Testing and packaging
- [x] Unit tests for `fmt.py`, graph scaling, priority names, incremental model updates
- [x] Sampler test (real samples are well-formed; NT snapshot agrees with psutil)
- [x] Offscreen smoke test: main window builds and every tab renders with real data
- [x] `build.ps1`: PyInstaller windowed folder build `dist\SystemMonitor\SystemMonitor.exe` with app icon
      (measured: about 50 MB private memory, about 0.3% CPU at a 1 s interval)
- [x] README with install / run / build steps
- [x] Trim the build size: 111 MB -> 52 MB (unused Qt modules, plugins, translations, OpenSSL removed)
- [x] App icon from the user's logo (`sysmon/assets/logo.png`), multi-size exe icon via `tools/make_ico.py`
- [x] `--selftest DIR` flag; `build.ps1` runs it on the trimmed exe and fails the build if any tab breaks

## Phase 8 — Windows integration (optional, user's choice)
- [ ] Start-menu shortcut / install script (user chose: not now; pin manually)
- [ ] (user chose: not now) Make Ctrl+Shift+Esc open System Monitor (Image File Execution Options `Debugger` for `taskmgr.exe`), with an undo script
- [ ] Single-instance: launching again focuses the existing window
- [ ] Start minimised to tray / tray icon with CPU meter
