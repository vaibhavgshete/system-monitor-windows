"""Application entry point and main window."""

from __future__ import annotations

import os
import sys

import psutil
from PySide6.QtCore import QSettings, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QCloseEvent, QFont, QKeySequence, QShortcut, QShowEvent
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QMainWindow,
    QMenu,
    QMessageBox,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import __version__, theme, winutil
from .filesystems import FileSystemsPage
from .processes import ProcessesPage
from .resources import ResourcesPage
from .sampler import Sampler, Snapshot

INTERVALS = [(500, "0.5 seconds"), (1000, "1 second"), (2000, "2 seconds"), (3000, "3 seconds"), (5000, "5 seconds")]
APPEARANCES = [("system", "Follow Windows"), ("light", "Light"), ("dark", "Dark")]
TABS = [("processes", "Processes"), ("resources", "Resources"), ("filesystems", "File Systems")]


class HeaderBar(QWidget):
    """GNOME-style header: centred view switcher, search + menu buttons on the right."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("HeaderBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        switcher = QWidget()
        switcher.setObjectName("Switcher")
        sw = QHBoxLayout(switcher)
        sw.setContentsMargins(0, 0, 0, 0)
        sw.setSpacing(4)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        self.tab_buttons: list[QToolButton] = []
        for i, (_key, label) in enumerate(TABS):
            b = QToolButton()
            b.setText(label)
            b.setCheckable(True)
            b.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setToolTip(f"{label} (Ctrl+{i + 1})")
            self.group.addButton(b, i)
            self.tab_buttons.append(b)
            sw.addWidget(b)

        self.search_button = QToolButton()
        self.search_button.setObjectName("HeaderButton")
        self.search_button.setCheckable(True)
        self.search_button.setToolTip("Search (Ctrl+F)")
        self.menu_button = QToolButton()
        self.menu_button.setObjectName("HeaderButton")
        self.menu_button.setToolTip("Main Menu")
        self.menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)

        right = QWidget()
        rl = QHBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(6)
        rl.addStretch(1)
        rl.addWidget(self.search_button)
        rl.addWidget(self.menu_button)
        left = QWidget()
        for w in (left, right):
            w.setFixedWidth(90)  # equal side widths keep the switcher truly centred

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.addWidget(left)
        lay.addStretch(1)
        lay.addWidget(switcher)
        lay.addStretch(1)
        lay.addWidget(right)

        theme.manager.changed.connect(self._on_theme)
        self._on_theme()

    def _on_theme(self) -> None:
        for b, (key, _label) in zip(self.tab_buttons, TABS):
            b.setIcon(theme.icon(key))
        self.search_button.setIcon(theme.icon("search"))
        self.menu_button.setIcon(theme.icon("menu"))


class PreferencesDialog(QDialog):
    def __init__(self, settings: QSettings, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.setMinimumWidth(380)

        self.interval = QComboBox()
        for ms, label in INTERVALS:
            self.interval.addItem(label, ms)
        self.interval.setCurrentIndex(max(0, self.interval.findData(settings.value("interval", 1000, type=int))))

        self.appearance = QComboBox()
        for key, label in APPEARANCES:
            self.appearance.addItem(label, key)
        self.appearance.setCurrentIndex(max(0, self.appearance.findData(theme.manager.mode)))

        self.divide = QCheckBox("Divide CPU usage by number of CPUs")
        self.divide.setChecked(settings.value("divide_cpu", True, type=bool))
        self.divide.setToolTip("When off, one process fully using one core shows 100% (like `top`).")

        form = QFormLayout()
        form.setVerticalSpacing(12)
        form.setHorizontalSpacing(16)
        form.addRow("Update interval", self.interval)
        form.addRow("Appearance", self.appearance)
        form.addRow("", self.divide)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 16)
        lay.addLayout(form)
        lay.addSpacing(10)
        lay.addWidget(buttons)


class MainWindow(QMainWindow):
    _stop_sampler = Signal()
    _set_interval = Signal(int)
    _set_divide_cpu = Signal(bool)

    def __init__(self, settings: QSettings | None = None) -> None:
        super().__init__()
        self.settings = settings or QSettings("SystemMonitor", "SystemMonitor")
        theme.manager.set_mode(str(self.settings.value("appearance", "system")))
        self.setWindowTitle("System Monitor" + (" (Administrator)" if winutil.is_admin() else ""))
        self.setWindowIcon(theme.app_icon())
        self.resize(1000, 720)
        self.setMinimumSize(640, 420)

        self.header = HeaderBar()
        self.processes = ProcessesPage(self.settings)
        self.resources = ResourcesPage(psutil.cpu_count() or 1, self.settings)
        self.filesystems = FileSystemsPage()
        self.stack = QStackedWidget()
        for page in (self.processes, self.resources, self.filesystems):
            self.stack.addWidget(page)

        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.header)
        lay.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.header.group.idClicked.connect(self.set_tab)
        self.header.search_button.toggled.connect(self.processes.set_search_visible)
        self.processes.search_visibility_changed.connect(self._sync_search_button)
        self._build_menu()
        self._build_shortcuts()

        self._pending: Snapshot | None = None
        self._start_sampler()

        geometry = self.settings.value("window/geometry")
        if geometry is not None:
            self.restoreGeometry(geometry)
        self.set_tab(self.settings.value("window/tab", 0, type=int))
        theme.manager.changed.connect(self._apply_title_bar)

    # -- setup -----------------------------------------------------------------------------

    def _build_menu(self) -> None:
        menu = QMenu(self)
        self.view_group = QActionGroup(self)
        self.view_actions: list[QAction] = []
        current = str(self.settings.value("processes/mode", "all"))
        for key, label in [("all", "All Processes"), ("mine", "My Processes"), ("active", "Active Processes")]:
            act = QAction(label, self, checkable=True)
            act.setChecked(key == current)
            act.triggered.connect(lambda _c=False, k=key: self._set_view_mode(k))
            self.view_group.addAction(act)
            self.view_actions.append(act)
            menu.addAction(act)
        self.processes.proxy.set_mode(current)
        menu.addSeparator()
        self.tree_action = QAction("Show Dependencies", self, checkable=True)
        self.tree_action.setToolTip("Show processes as a tree of parents and children")
        self.tree_action.setChecked(self.settings.value("processes/tree", False, type=bool))
        self.tree_action.toggled.connect(self._set_tree)
        self.processes.set_tree(self.tree_action.isChecked())
        menu.addAction(self.tree_action)
        self.view_actions.append(self.tree_action)
        menu.addSeparator()
        if not winutil.is_admin():
            menu.addAction("Restart as Administrator", self._restart_as_admin)
            menu.addSeparator()
        menu.addAction("Preferences", self._preferences, QKeySequence("Ctrl+,"))
        menu.addAction("About System Monitor", self._about)
        menu.addSeparator()
        menu.addAction("Quit", self.close, QKeySequence("Ctrl+Q"))
        self.header.menu_button.setMenu(menu)

    def _build_shortcuts(self) -> None:
        for i in range(len(TABS)):
            QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self, lambda i=i: self.set_tab(i))
        QShortcut(QKeySequence("Ctrl+F"), self, self._toggle_search)
        QShortcut(QKeySequence("Ctrl+Q"), self, self.close)
        QShortcut(QKeySequence("Ctrl+,"), self, self._preferences)
        end = QShortcut(QKeySequence(Qt.Key.Key_Delete), self.processes.view, lambda: self.processes.end_selected())
        end.setContext(Qt.ShortcutContext.WidgetShortcut)

    def _start_sampler(self) -> None:
        self.thread_ = QThread(self)
        self.sampler = Sampler(
            self.settings.value("interval", 1000, type=int),
            self.settings.value("divide_cpu", True, type=bool),
        )
        self.sampler.moveToThread(self.thread_)
        self.thread_.started.connect(self.sampler.start)
        self.sampler.sampled.connect(self._on_snapshot)
        self._stop_sampler.connect(self.sampler.stop, Qt.ConnectionType.BlockingQueuedConnection)
        self._set_interval.connect(self.sampler.set_interval)
        self._set_divide_cpu.connect(self.sampler.set_divide_cpu)
        self.thread_.start()

    # -- behaviour -------------------------------------------------------------------------

    def _on_snapshot(self, snap: Snapshot) -> None:
        self.resources.update_snapshot(snap)  # graphs keep their history even when hidden
        if snap.disks is not None:
            self.filesystems.update_disks(snap.disks)
        if self.stack.currentWidget() is self.processes and not self.isMinimized():
            self.processes.update_processes(snap.processes)
            self._pending = None
        else:
            self._pending = snap  # applied when the Processes tab is shown again

    def set_tab(self, i: int) -> None:
        i = max(0, min(i, len(TABS) - 1))
        self.stack.setCurrentIndex(i)
        self.header.tab_buttons[i].setChecked(True)
        on_processes = self.stack.currentWidget() is self.processes
        self.header.search_button.setVisible(on_processes)
        for act in self.view_actions:
            act.setEnabled(on_processes)
        if on_processes:
            if self._pending is not None:
                self.processes.update_processes(self._pending.processes)
                self._pending = None
            self.processes.view.setFocus()

    def _toggle_search(self) -> None:
        if self.stack.currentWidget() is not self.processes:
            self.set_tab(0)
            self.header.search_button.setChecked(True)
        else:
            self.header.search_button.toggle()

    def _sync_search_button(self, on: bool) -> None:
        b = self.header.search_button
        b.blockSignals(True)
        b.setChecked(on)
        b.blockSignals(False)

    def _set_view_mode(self, mode: str) -> None:
        self.processes.proxy.set_mode(mode)
        self.settings.setValue("processes/mode", mode)

    def _set_tree(self, on: bool) -> None:
        self.processes.set_tree(on)
        self.settings.setValue("processes/tree", on)

    def _preferences(self) -> None:
        dlg = PreferencesDialog(self.settings, self)

        def interval_changed() -> None:
            ms = int(dlg.interval.currentData())
            self.settings.setValue("interval", ms)
            self._set_interval.emit(ms)

        def appearance_changed() -> None:
            mode = str(dlg.appearance.currentData())
            self.settings.setValue("appearance", mode)
            theme.manager.set_mode(mode)

        def divide_changed(on: bool) -> None:
            self.settings.setValue("divide_cpu", on)
            self._set_divide_cpu.emit(on)

        dlg.interval.currentIndexChanged.connect(lambda _i: interval_changed())
        dlg.appearance.currentIndexChanged.connect(lambda _i: appearance_changed())
        dlg.divide.toggled.connect(divide_changed)
        dlg.exec()

    def _restart_as_admin(self) -> None:
        if winutil.relaunch_as_admin():
            self.close()

    def _about(self) -> None:
        QMessageBox.about(
            self,
            "About System Monitor",
            f"<h3>System Monitor {__version__}</h3>"
            "<p>A clean, readable Task Manager replacement for Windows,<br>"
            "inspired by GNOME System Monitor.</p>"
            f"<p>Python {sys.version.split()[0]} · psutil {psutil.__version__}</p>",
        )

    def _apply_title_bar(self) -> None:
        winutil.set_dark_title_bar(int(self.winId()), theme.current().dark)

    def showEvent(self, e: QShowEvent) -> None:
        super().showEvent(e)
        self._apply_title_bar()

    def closeEvent(self, e: QCloseEvent) -> None:
        self.settings.setValue("window/geometry", self.saveGeometry())
        self.settings.setValue("window/tab", self.stack.currentIndex())
        self.processes.save_state()
        self._stop_sampler.emit()
        self.thread_.quit()
        self.thread_.wait(3000)
        super().closeEvent(e)


def _selftest_capture(window: MainWindow, out_dir: str) -> None:
    for i, (key, _label) in enumerate(TABS):
        window.set_tab(i)
        QApplication.processEvents()
        window.grab().save(os.path.join(out_dir, f"selftest-{key}.png"))
    window.close()
    QApplication.exit(0)


def main() -> None:
    # `--selftest DIR`: run with throwaway settings, save a screenshot of each tab to DIR, exit.
    # Used to verify packaged builds.
    args = sys.argv[1:]
    selftest = args[args.index("--selftest") + 1] if "--selftest" in args[:-1] else None

    winutil.set_app_user_model_id("SystemMonitor.App")
    app = QApplication(sys.argv)
    app.setApplicationName("System Monitor")
    app.setOrganizationName("SystemMonitor")
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 10))
    app.setWindowIcon(theme.app_icon())

    settings = None
    if selftest:
        os.makedirs(selftest, exist_ok=True)
        settings = QSettings(os.path.join(selftest, "selftest.ini"), QSettings.Format.IniFormat)
    window = MainWindow(settings)
    window.show()
    if selftest:
        QTimer.singleShot(6000, lambda: _selftest_capture(window, selftest))
    sys.exit(app.exec())
