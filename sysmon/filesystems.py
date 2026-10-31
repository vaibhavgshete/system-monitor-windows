"""File Systems tab: one row per drive with a usage bar."""

from __future__ import annotations

import os
from enum import IntEnum

from PySide6.QtCore import (
    QAbstractTableModel,
    QFileInfo,
    QModelIndex,
    QPersistentModelIndex,
    QRectF,
    QSortFilterProxyModel,
    Qt,
)
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QFileIconProvider,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTreeView,
)

from . import fmt, theme
from .processes import SORT_ROLE
from .sampler import DiskInfo


class FsCol(IntEnum):
    DEVICE = 0
    DIRECTORY = 1
    TYPE = 2
    TOTAL = 3
    AVAILABLE = 4
    USED = 5
    BAR = 6


_TITLES = ["Device", "Directory", "Type", "Total", "Available", "Used", ""]
_WIDTHS = [190, 110, 70, 90, 90, 90]
USAGE_ROLE = Qt.ItemDataRole.UserRole + 2


def _device_name(d: DiskInfo) -> str:
    letter = d.mountpoint.rstrip("\\/")
    return f"{d.label or 'Local Disk'} ({letter})" if len(letter) == 2 and letter[1] == ":" else d.device


class FileSystemModel(QAbstractTableModel):
    def __init__(self) -> None:
        super().__init__()
        self._rows: list[DiskInfo] = []
        self._icons = QFileIconProvider()
        self._icon_cache: dict[str, object] = {}

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._rows)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:
        return 0 if parent.isValid() else len(FsCol)

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return _TITLES[section]
        return None

    def disk(self, row: int) -> DiskInfo:
        return self._rows[row]

    def data(self, index: QModelIndex | QPersistentModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        d = self._rows[index.row()]
        col = FsCol(index.column())
        if role == Qt.ItemDataRole.DisplayRole:
            match col:
                case FsCol.DEVICE:
                    return _device_name(d)
                case FsCol.DIRECTORY:
                    return d.mountpoint
                case FsCol.TYPE:
                    return d.fstype
                case FsCol.TOTAL:
                    return fmt.size(d.total)
                case FsCol.AVAILABLE:
                    return fmt.size(d.free)
                case FsCol.USED:
                    return fmt.size(d.used)
            return None
        if role in (SORT_ROLE, USAGE_ROLE):
            match col:
                case FsCol.TOTAL:
                    return d.total
                case FsCol.AVAILABLE:
                    return d.free
                case FsCol.USED | FsCol.BAR:
                    return d.used / d.total if d.total else 0.0
                case _:
                    return str(self.data(index, Qt.ItemDataRole.DisplayRole)).lower()
        if role == Qt.ItemDataRole.DecorationRole and col == FsCol.DEVICE:
            icon = self._icon_cache.get(d.mountpoint)
            if icon is None:
                icon = self._icon_cache[d.mountpoint] = self._icons.icon(QFileInfo(d.mountpoint))
            return icon
        if role == Qt.ItemDataRole.TextAlignmentRole and col in (FsCol.TOTAL, FsCol.AVAILABLE, FsCol.USED):
            return int(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        return None

    def update(self, disks: list[DiskInfo]) -> None:
        if [d.mountpoint for d in disks] == [d.mountpoint for d in self._rows]:
            self._rows = disks
            if disks:
                self.dataChanged.emit(self.index(0, 0), self.index(len(disks) - 1, len(FsCol) - 1))
        else:
            self.beginResetModel()
            self._rows = disks
            self.endResetModel()


class UsageBarDelegate(QStyledItemDelegate):
    """Rounded usage bar with the percentage centred on it."""

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index: QModelIndex) -> None:
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawPrimitive(QStyle.PrimitiveElement.PE_PanelItemViewItem, opt, painter, opt.widget)

        frac = float(index.data(USAGE_ROLE) or 0.0)
        t = theme.current()
        r = QRectF(opt.rect).adjusted(6, 5, -10, -5)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(t.trough))
        painter.drawRoundedRect(r, 3, 3)
        if frac > 0:
            fill = QRectF(r)
            fill.setWidth(max(r.width() * min(frac, 1.0), 3))
            painter.setBrush(QColor(t.destructive if frac >= 0.9 else t.accent))
            painter.drawRoundedRect(fill, 3, 3)
        painter.setPen(QColor(t.text))
        painter.drawText(r, Qt.AlignmentFlag.AlignCenter, f"{frac * 100:.0f}%")
        painter.restore()


class FileSystemsPage(QTreeView):
    def __init__(self) -> None:
        super().__init__()
        self.model_ = FileSystemModel()
        proxy = QSortFilterProxyModel(self)
        proxy.setSourceModel(self.model_)
        proxy.setSortRole(SORT_ROLE)
        self.setModel(proxy)
        self.setRootIsDecorated(False)
        self.setUniformRowHeights(True)
        self.setSortingEnabled(True)
        self.sortByColumn(FsCol.DIRECTORY, Qt.SortOrder.AscendingOrder)
        self.setAllColumnsShowFocus(True)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setItemDelegateForColumn(FsCol.BAR, UsageBarDelegate(self))
        self.doubleClicked.connect(self._open)
        header = self.header()
        header.setStretchLastSection(True)
        header.setHighlightSections(False)
        header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        for col, w in enumerate(_WIDTHS):
            header.resizeSection(col, w)
        theme.manager.changed.connect(self.viewport().update)

    def update_disks(self, disks: list[DiskInfo]) -> None:
        self.model_.update(disks)

    def _open(self, index: QModelIndex) -> None:
        proxy = self.model()
        d = self.model_.disk(proxy.mapToSource(index).row())
        try:
            os.startfile(d.mountpoint)  # type: ignore[attr-defined]
        except OSError:
            pass
