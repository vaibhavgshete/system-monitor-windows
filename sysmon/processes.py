"""Processes tab: incremental list/tree model, search/filter proxy, view and process actions."""

from __future__ import annotations

import datetime
import os
from enum import IntEnum

import psutil
from PySide6.QtCore import (
    QAbstractItemModel,
    QEvent,
    QFileInfo,
    QModelIndex,
    QPersistentModelIndex,
    QSettings,
    QSortFilterProxyModel,
    Qt,
    Signal,
)
from PySide6.QtGui import QAction, QActionGroup, QColor, QFont, QGuiApplication, QIcon, QKeyEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileIconProvider,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QToolButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from . import fmt, ntproc, theme, winutil
from .sampler import ProcInfo

SORT_ROLE = Qt.ItemDataRole.UserRole + 1


class Col(IntEnum):
    NAME = 0
    USER = 1
    CPU = 2
    PID = 3
    MEMORY = 4
    READ_TOTAL = 5
    WRITE_TOTAL = 6
    READ = 7
    WRITE = 8
    PRIORITY = 9
    GPU = 10


TITLES = {
    Col.NAME: "Process Name",
    Col.USER: "User",
    Col.CPU: "% CPU",
    Col.PID: "ID",
    Col.MEMORY: "Memory",
    Col.READ_TOTAL: "Disk read total",
    Col.WRITE_TOTAL: "Disk write total",
    Col.READ: "Disk read",
    Col.WRITE: "Disk write",
    Col.PRIORITY: "Priority",
    Col.GPU: "% GPU",
}
DEFAULT_WIDTHS = {
    Col.NAME: 230, Col.USER: 130, Col.CPU: 70, Col.PID: 70, Col.MEMORY: 95, Col.READ_TOTAL: 115,
    Col.WRITE_TOTAL: 115, Col.READ: 95, Col.WRITE: 95, Col.PRIORITY: 80,
    Col.GPU: 70,
}
HIDDEN_BY_DEFAULT = {Col.USER, Col.GPU}

# (label, psutil priority class name, Windows base priority)
PRIORITIES = [
    ("Realtime", "REALTIME_PRIORITY_CLASS", 24),
    ("Very High", "HIGH_PRIORITY_CLASS", 13),
    ("High", "ABOVE_NORMAL_PRIORITY_CLASS", 10),
    ("Normal", "NORMAL_PRIORITY_CLASS", 8),
    ("Low", "BELOW_NORMAL_PRIORITY_CLASS", 6),
    ("Very Low", "IDLE_PRIORITY_CLASS", 4),
]


def priority_name(base: int | None) -> str | None:
    if base is None:
        return None
    for label, _cls, value in PRIORITIES:
        if base >= value:
            return label
    return "Very Low"


def _raw(p: ProcInfo, col: Col):
    match col:
        case Col.NAME:
            return p.name
        case Col.USER:
            return p.user.split("\\")[-1] if p.user else None
        case Col.CPU:
            return p.cpu
        case Col.PID:
            return p.pid
        case Col.MEMORY:
            return p.memory
        case Col.READ_TOTAL:
            return p.read_total
        case Col.WRITE_TOTAL:
            return p.write_total
        case Col.READ:
            return p.read_rate
        case Col.WRITE:
            return p.write_rate
        case Col.PRIORITY:
            return p.priority
        case Col.GPU:
            return p.gpu


def _display(col: Col, v) -> str:
    if v is None:
        return fmt.NA
    match col:
        case Col.CPU | Col.GPU:
            return f"{v:.2f}"
        case Col.MEMORY | Col.READ_TOTAL | Col.WRITE_TOTAL:
            return fmt.size(v) if v else fmt.NA
        case Col.READ | Col.WRITE:
            return fmt.rate(v) if v else fmt.NA
        case Col.PRIORITY:
            return priority_name(v) or fmt.NA
    return str(v)


class IconCache:
    """App icons from exe files (shell icons on Windows), cached by path."""

    def __init__(self) -> None:
        self._provider = QFileIconProvider()
        self._cache: dict[str, QIcon] = {}
        self._generic: QIcon | None = None

    def generic(self) -> QIcon:
        if self._generic is None:
            self._generic = theme.icon("app", "#3584e4")
        return self._generic

    def get(self, exe: str | None) -> QIcon:
        if not exe:
            return self.generic()
        icon = self._cache.get(exe)
        if icon is None:
            icon = self._provider.icon(QFileInfo(exe))
            if icon.isNull():
                icon = self.generic()
            self._cache[exe] = icon
        return icon


class _Node:
    __slots__ = ("proc", "parent", "children", "row")

    def __init__(self, proc: ProcInfo | None) -> None:
        self.proc = proc
        self.parent: _Node | None = None  # None = root, or detached during an update
        self.children: list[_Node] = []
        self.row = 0


class ProcessModel(QAbstractItemModel):
    """Processes as a flat list or a parent/child tree ("Show Dependencies").

    Nodes are keyed by PID and updated incrementally (insert/remove per row), so selection,
    expansion and scroll position survive refreshes. Flat mode is just a tree of depth one.
    """

    def __init__(self) -> None:
        super().__init__()
        self._root = _Node(None)
        self._nodes: dict[int, _Node] = {}
        self._tree = False
        self._icons = IconCache()
        self._italic = QFont()
        self._italic.setItalic(True)

    @property
    def tree(self) -> bool:
        return self._tree

    def set_tree(self, on: bool, procs: list[ProcInfo]) -> None:
        self.beginResetModel()
        self._tree = on
        self._root = _Node(None)
        self._nodes = {}
        self.endResetModel()
        self.update(procs)

    # -- QAbstractItemModel ------------------------------------------------------------------

    def _node(self, index: QModelIndex | QPersistentModelIndex) -> _Node:
        return index.internalPointer() if index.isValid() else self._root

    def _index_of(self, node: _Node) -> QModelIndex:
        return QModelIndex() if node is self._root else self.createIndex(node.row, 0, node)

    def index(self, row: int, column: int, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> QModelIndex:
        if parent.isValid() and parent.column() != 0:
            return QModelIndex()
        node = self._node(parent)
        if 0 <= row < len(node.children) and 0 <= column < len(Col):
            return self.createIndex(row, column, node.children[row])
        return QModelIndex()

    def parent(self, index=None):  # also shadows QObject.parent(), hence the optional argument
        if index is None:
            return super().parent()
        if not index.isValid():
            return QModelIndex()
        p = index.internalPointer().parent
        return QModelIndex() if p is None or p is self._root else self.createIndex(p.row, 0, p)

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        if parent.isValid() and parent.column() != 0:
            return 0
        return len(self._node(parent).children)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        return len(Col)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return TITLES[Col(section)]
        return None

    def proc_at(self, index: QModelIndex | QPersistentModelIndex) -> ProcInfo:
        return index.internalPointer().proc

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        p: ProcInfo = index.internalPointer().proc
        col = Col(index.column())
        if role == Qt.ItemDataRole.DisplayRole:
            return _display(col, _raw(p, col))
        if role == SORT_ROLE:
            v = _raw(p, col)
            if col in (Col.NAME, Col.USER):
                return (v or "").lower()
            return -1 if v is None else v
        if role == Qt.ItemDataRole.DecorationRole and col == Col.NAME:
            return self._icons.get(p.exe)
        if role == Qt.ItemDataRole.TextAlignmentRole and col not in (Col.NAME, Col.USER, Col.PRIORITY):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        if role in (Qt.ItemDataRole.FontRole, Qt.ItemDataRole.ForegroundRole):
            if _display(col, _raw(p, col)) == fmt.NA:
                return self._italic if role == Qt.ItemDataRole.FontRole else QColor(theme.current().dim)
        if role == Qt.ItemDataRole.ToolTipRole and col == Col.NAME:
            return p.exe or p.name
        return None

    # -- incremental update ------------------------------------------------------------------

    def _wanted_parent(self, p: ProcInfo, incoming: dict[int, ProcInfo]) -> int | None:
        if not self._tree or p.ppid is None or p.ppid == p.pid:
            return None
        parent = incoming.get(p.ppid)
        if parent is None:
            return None
        if parent.create_time is not None and p.create_time is not None and parent.create_time > p.create_time:
            return None  # the real parent exited and its PID was reused by a newer process
        return p.ppid

    def update(self, procs: list[ProcInfo]) -> None:
        incoming = {p.pid: p for p in procs}
        want = {p.pid: self._wanted_parent(p, incoming) for p in procs}

        # 1. Detach nodes that vanished or got a different parent. Children are visited before
        #    their parents, so a node that moves only carries children that stay with it.
        for node in self._post_order():
            pid = node.proc.pid
            current = None if node.parent is self._root else node.parent.proc.pid
            if pid not in incoming or want[pid] != current:
                self._detach(node)
                if pid not in incoming:
                    del self._nodes[pid]

        # 2. Fresh data for everything that survived.
        for pid, node in self._nodes.items():
            node.proc = incoming[pid]

        # 3. Attach new and moved nodes, parents before children, one block per parent.
        pending = [n for n in self._nodes.values() if n.parent is None]
        for p in procs:
            if p.pid not in self._nodes:
                node = self._nodes[p.pid] = _Node(p)
                pending.append(node)
        while pending:
            ready: dict[int, tuple[_Node, list[_Node]]] = {}
            rest = []
            for n in pending:
                ppid = want[n.proc.pid]
                parent = self._root if ppid is None else self._nodes[ppid]
                if self._attached(parent):
                    ready.setdefault(id(parent), (parent, []))[1].append(n)
                else:
                    rest.append(n)
            if not ready:  # inconsistent parent data (a cycle): show the rest at top level
                ready = {id(self._root): (self._root, rest)}
                rest = []
            for parent, nodes in ready.values():
                self._attach(parent, nodes)
            pending = rest

        # 4. Announce changed values, one contiguous range per parent.
        stack = [self._root]
        while stack:
            node = stack.pop()
            if node.children:
                parent = self._index_of(node)
                self.dataChanged.emit(
                    self.index(0, 0, parent), self.index(len(node.children) - 1, len(Col) - 1, parent)
                )
                stack.extend(c for c in node.children if c.children)

    def _post_order(self) -> list[_Node]:
        out: list[_Node] = []
        stack: list[tuple[_Node, bool]] = [(c, False) for c in reversed(self._root.children)]
        while stack:
            node, children_done = stack.pop()
            if children_done or not node.children:
                out.append(node)
            else:
                stack.append((node, True))
                stack.extend((c, False) for c in reversed(node.children))
        return out

    def _attached(self, node: _Node) -> bool:
        while node is not self._root:
            if node.parent is None:
                return False
            node = node.parent
        return True

    def _detach(self, node: _Node) -> None:
        parent = node.parent
        assert parent is not None
        row = node.row
        self.beginRemoveRows(self._index_of(parent), row, row)
        del parent.children[row]
        for i in range(row, len(parent.children)):
            parent.children[i].row = i
        node.parent = None
        self.endRemoveRows()

    def _attach(self, parent: _Node, nodes: list[_Node]) -> None:
        first = len(parent.children)
        self.beginInsertRows(self._index_of(parent), first, first + len(nodes) - 1)
        for i, n in enumerate(nodes):
            n.parent = parent
            n.row = first + i
        parent.children.extend(nodes)
        self.endInsertRows()


class ProcessFilter(QSortFilterProxyModel):
    """Search text + view mode ('all', 'mine', 'active')."""

    def __init__(self, me: str | None) -> None:
        super().__init__()
        self._me = me
        self._text = ""
        self.mode = "all"
        self.setSortRole(SORT_ROLE)
        self.setDynamicSortFilter(True)
        self.setRecursiveFilteringEnabled(True)  # tree mode: keep ancestors of matching processes

    def set_text(self, text: str) -> None:
        self._refilter(lambda: setattr(self, "_text", text.strip().lower()))

    def set_mode(self, mode: str) -> None:
        self._refilter(lambda: setattr(self, "mode", mode))

    def _refilter(self, change) -> None:
        if hasattr(self, "beginFilterChange"):  # Qt 6.9+, where invalidateFilter() is deprecated
            self.beginFilterChange()
            change()
            self.endFilterChange()
        else:
            change()
            self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex | QPersistentModelIndex) -> bool:
        model: ProcessModel = self.sourceModel()
        p = model.proc_at(model.index(source_row, 0, source_parent))
        if self.mode == "mine" and (self._me is None or p.user != self._me):
            return False
        if self.mode == "active" and p.cpu < 0.01 and not (p.read_rate or p.write_rate):
            return False
        if self._text:
            return self._text in p.name.lower() or str(p.pid).startswith(self._text)
        return True


def current_user() -> str | None:
    if ntproc.AVAILABLE:
        try:
            user = ntproc.process_users().get(os.getpid())
            if user:
                return user
        except OSError:
            pass
    try:
        return psutil.Process().username()
    except psutil.Error:
        return None


class ProcessView(QTreeView):
    type_to_search = Signal(str)

    def keyPressEvent(self, e: QKeyEvent) -> None:
        text = e.text()
        if text and text.isprintable() and not text.isspace() and not (
            e.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
        ):
            self.type_to_search.emit(text)
            return
        super().keyPressEvent(e)


def access_denied(parent: QWidget, what: str) -> None:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle("Access denied")
    box.setText(f"Could not {what}: access denied.")
    if winutil.is_admin():
        box.setInformativeText("This is a protected system process.")
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.exec()
        return
    box.setInformativeText("Processes owned by other users or by the system need administrator rights.")
    restart = box.addButton("Restart as Administrator", QMessageBox.ButtonRole.AcceptRole)
    restart.setObjectName("Suggested")
    box.addButton(QMessageBox.StandardButton.Close)
    box.exec()
    if box.clickedButton() is restart and winutil.relaunch_as_admin():
        QApplication.quit()


_HEADER_KEY = "processes/header-v2"  # bumped when the column set changed (GPU added)


class ProcessesPage(QWidget):
    search_visibility_changed = Signal(bool)

    def __init__(self, settings: QSettings) -> None:
        super().__init__()
        self._settings = settings
        self.model = ProcessModel()
        self.proxy = ProcessFilter(current_user())
        self.proxy.setSourceModel(self.model)

        # Search bar (hidden until Ctrl+F / the header search button / typing in the list).
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search processes by name or ID")
        self.search.setClearButtonEnabled(True)
        self.search.setMaximumWidth(380)
        self.search.textChanged.connect(self.proxy.set_text)
        self.search.installEventFilter(self)
        self.search_bar = QWidget()
        sb = QHBoxLayout(self.search_bar)
        sb.setContentsMargins(12, 8, 12, 8)
        sb.addStretch(1)
        sb.addWidget(self.search, 2)
        sb.addStretch(1)
        self.search_bar.hide()

        self.view = ProcessView()
        self.view.setModel(self.proxy)
        self.view.setRootIsDecorated(False)
        self.view.setUniformRowHeights(True)
        self.view.setSortingEnabled(True)
        self.view.setAllColumnsShowFocus(True)
        self.view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._context_menu)
        self.view.doubleClicked.connect(lambda _i: self.show_properties())
        self.view.type_to_search.connect(self._start_search_with)
        self.view.selectionModel().selectionChanged.connect(lambda *_: self._sync_buttons())
        self.view.setIndentation(18)

        # Tree mode: everything is expanded, except branches the user collapsed (remembered by PID).
        self._collapsed: set[int] = set()
        self._last: list[ProcInfo] = []
        self.view.collapsed.connect(lambda i: self._collapsed.add(self._pid(i)))
        self.view.expanded.connect(lambda i: self._collapsed.discard(self._pid(i)))
        self.proxy.rowsInserted.connect(self._on_rows_inserted)
        self.proxy.modelReset.connect(self._expand_all)

        header = self.view.header()
        header.setSectionsMovable(True)
        header.setHighlightSections(False)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        header.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        header.customContextMenuRequested.connect(self._header_menu)
        header.setStretchLastSection(True)
        for col, w in DEFAULT_WIDTHS.items():
            header.resizeSection(col, w)
        for col in HIDDEN_BY_DEFAULT:
            header.setSectionHidden(col, True)
        state = settings.value(_HEADER_KEY)
        if state is not None:
            header.restoreState(state)
        else:
            self.view.sortByColumn(Col.CPU, Qt.SortOrder.DescendingOrder)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)

        self.end_button = QPushButton("End Process")
        self.end_button.clicked.connect(lambda: self.end_selected())
        self.props_button = QToolButton()
        self.props_button.setObjectName("HeaderButton")
        self.props_button.setToolTip("Process Properties")
        self.props_button.clicked.connect(self.show_properties)
        bottom = QHBoxLayout()
        bottom.setContentsMargins(8, 8, 8, 8)
        bottom.addWidget(self.end_button)
        bottom.addStretch(1)
        bottom.addWidget(self.props_button)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self.search_bar)
        lay.addWidget(self.view, 1)
        sep = QWidget()
        sep.setObjectName("Separator")
        sep.setFixedHeight(1)
        lay.addWidget(sep)
        lay.addLayout(bottom)

        theme.manager.changed.connect(self._on_theme)
        self._on_theme()
        self._sync_buttons()

    # -- data ------------------------------------------------------------------------------

    def update_processes(self, procs: list[ProcInfo]) -> None:
        self._last = procs
        self.model.update(procs)
        self._sync_buttons()

    def save_state(self) -> None:
        self._settings.setValue(_HEADER_KEY, self.view.header().saveState())

    # -- tree ("Show Dependencies") --------------------------------------------------------

    def set_tree(self, on: bool) -> None:
        if on == self.model.tree:
            return
        self.view.setRootIsDecorated(on)
        if on and self.view.header().sectionSize(Col.NAME) < 320:
            self.view.header().resizeSection(Col.NAME, 320)  # room for indented names
        self.model.set_tree(on, self._last)
        self._expand_all()

    def _pid(self, proxy_index: QModelIndex) -> int:
        return self.model.proc_at(self.proxy.mapToSource(proxy_index)).pid

    def _expand_subtree(self, index: QModelIndex) -> None:
        if self.proxy.rowCount(index) == 0 or self._pid(index) in self._collapsed:
            return
        self.view.expand(index)
        for r in range(self.proxy.rowCount(index)):
            self._expand_subtree(self.proxy.index(r, 0, index))

    def _expand_all(self) -> None:
        if not self.model.tree:
            return
        for r in range(self.proxy.rowCount()):
            self._expand_subtree(self.proxy.index(r, 0))

    def _on_rows_inserted(self, parent: QModelIndex, first: int, last: int) -> None:
        if not self.model.tree:
            return
        if parent.isValid() and self._pid(parent) not in self._collapsed:
            self.view.expand(parent)
        for r in range(first, last + 1):
            self._expand_subtree(self.proxy.index(r, 0, parent))

    # -- search ----------------------------------------------------------------------------

    def set_search_visible(self, on: bool) -> None:
        self.search_bar.setVisible(on)
        if on:
            self.search.setFocus()
            self.search.selectAll()
        else:
            self.search.clear()
            self.view.setFocus()
        self.search_visibility_changed.emit(on)

    def _start_search_with(self, text: str) -> None:
        self.search_bar.show()
        self.search.setFocus()
        self.search.setText(self.search.text() + text)
        self.search_visibility_changed.emit(True)

    def eventFilter(self, obj, event) -> bool:
        if obj is self.search and event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self.set_search_visible(False)
                return True
            if event.key() in (Qt.Key.Key_Down, Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self.view.setFocus()
                if not self.view.selectionModel().hasSelection() and self.proxy.rowCount():
                    self.view.setCurrentIndex(self.proxy.index(0, 0))
                return True
        return super().eventFilter(obj, event)

    # -- selection & actions ---------------------------------------------------------------

    def selected(self) -> list[ProcInfo]:
        rows = self.view.selectionModel().selectedRows()
        return [self.model.proc_at(self.proxy.mapToSource(i)) for i in rows]

    def _sync_buttons(self) -> None:
        has = self.view.selectionModel().hasSelection()
        self.end_button.setEnabled(has)
        self.props_button.setEnabled(len(self.view.selectionModel().selectedRows()) == 1)

    def _on_theme(self) -> None:
        self.props_button.setIcon(theme.icon("info"))
        self.view.viewport().update()

    def end_selected(self, tree: bool = False) -> None:
        procs = self.selected()
        if not procs:
            return
        if len(procs) == 1:
            p = procs[0]
            what = "process tree of" if tree else "process"
            question = f"End the selected {what} “{p.name}” (PID {p.pid})?"
        else:
            question = f"End the {len(procs)} selected processes{' and their children' if tree else ''}?"
        box = QMessageBox(self)
        box.setWindowTitle("End Process")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(question)
        box.setInformativeText(
            "Ending a process may destroy unsaved data, break the session or introduce a "
            "security risk. Only unresponsive processes should be ended."
        )
        box.addButton(QMessageBox.StandardButton.Cancel)
        ok = box.addButton("End Process", QMessageBox.ButtonRole.DestructiveRole)
        ok.setObjectName("Destructive")
        box.setDefaultButton(QMessageBox.StandardButton.Cancel)
        box.exec()
        if box.clickedButton() is not ok:
            return

        denied = False
        for p in procs:
            try:
                proc = psutil.Process(p.pid)
                targets = proc.children(recursive=True) + [proc] if tree else [proc]
                for t in targets:
                    try:
                        t.kill()
                    except psutil.NoSuchProcess:
                        pass
            except psutil.NoSuchProcess:
                pass
            except psutil.AccessDenied:
                denied = True
        if denied:
            access_denied(self, "end the process")

    def set_priority(self, class_name: str) -> None:
        cls = getattr(psutil, class_name, None)
        if cls is None:
            return
        for p in self.selected():
            try:
                psutil.Process(p.pid).nice(cls)
            except psutil.NoSuchProcess:
                pass
            except psutil.AccessDenied:
                access_denied(self, "change the priority")
                return

    def show_properties(self) -> None:
        procs = self.selected()
        if len(procs) == 1:
            PropertiesDialog(procs[0], self).exec()

    def _context_menu(self, pos) -> None:
        procs = self.selected()
        if not procs:
            return
        menu = QMenu(self)
        menu.addAction("End Process", lambda: self.end_selected())
        menu.addAction("End Process Tree", lambda: self.end_selected(tree=True))
        menu.addSeparator()

        prio = menu.addMenu("Change Priority")
        group = QActionGroup(prio)
        current = priority_name(procs[0].priority) if len(procs) == 1 else None
        for label, cls, _value in PRIORITIES:
            act = QAction(label, prio, checkable=True)
            act.setChecked(label == current)
            act.triggered.connect(lambda _c=False, c=cls: self.set_priority(c))
            group.addAction(act)
            prio.addAction(act)

        menu.addSeparator()
        exe = procs[0].exe if len(procs) == 1 else None
        loc = menu.addAction("Open File Location", lambda: winutil.show_in_explorer(exe or ""))
        loc.setEnabled(bool(exe))
        menu.addAction("Copy Name", lambda: QGuiApplication.clipboard().setText("\n".join(p.name for p in procs)))
        menu.addAction("Copy ID", lambda: QGuiApplication.clipboard().setText("\n".join(str(p.pid) for p in procs)))
        menu.addSeparator()
        props = menu.addAction("Properties", self.show_properties)
        props.setEnabled(len(procs) == 1)
        menu.exec(self.view.viewport().mapToGlobal(pos))

    def _header_menu(self, pos) -> None:
        header = self.view.header()
        menu = QMenu(self)
        for col in Col:
            if col == Col.NAME:
                continue
            act = menu.addAction(TITLES[col])
            act.setCheckable(True)
            act.setChecked(not header.isSectionHidden(col))
            act.toggled.connect(lambda on, c=col: header.setSectionHidden(c, not on))
        menu.exec(header.mapToGlobal(pos))


class PropertiesDialog(QDialog):
    def __init__(self, p: ProcInfo, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{p.name} (PID {p.pid})")
        self.setMinimumWidth(520)

        started = cmdline = status = None
        try:
            proc = psutil.Process(p.pid)
            started = datetime.datetime.fromtimestamp(proc.create_time()).strftime("%Y-%m-%d %H:%M:%S")
            status = proc.status().capitalize()
            cmdline = " ".join(proc.cmdline()) or None
        except psutil.Error:
            pass

        rows = [
            ("Process Name", p.name),
            ("User", p.user),
            ("Status", status),
            ("Memory", fmt.size(p.memory) if p.memory is not None else None),
            ("CPU", fmt.percent(p.cpu, 2)),
            ("Started", started),
            ("ID", str(p.pid)),
            ("Parent ID", str(p.ppid) if p.ppid is not None else None),
            ("Threads", str(p.threads) if p.threads is not None else None),
            ("Handles", str(p.handles) if p.handles is not None else None),
            ("Priority", priority_name(p.priority)),
            ("Path", p.exe),
            ("Command Line", cmdline),
        ]
        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(8)
        for label, value in rows:
            key = QLabel(label)
            key.setProperty("dim", True)
            val = QLabel(value or fmt.NA)
            val.setWordWrap(True)
            val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            form.addRow(key, val)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 20, 20, 16)
        lay.addLayout(form)
        lay.addSpacing(8)
        lay.addWidget(buttons)
