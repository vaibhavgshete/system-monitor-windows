"""Resources tab: collapsible CPU / Memory and Swap / Network / Disk sections."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSettings, QSize, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from . import fmt, theme
from .graph import HistoryGraph
from .gpu import GpuInfo
from .sampler import Snapshot


class Swatch(QWidget):
    """Colour key. With `fraction` set it becomes a small donut chart (used for memory/swap)."""

    def __init__(self, color: QColor, size: int = 18, fraction: float | None = None) -> None:
        super().__init__()
        self._color = QColor(color)
        self._fraction = fraction
        self.setFixedSize(QSize(size, size))
        theme.manager.changed.connect(self.update)

    def set_fraction(self, f: float) -> None:
        self._fraction = max(0.0, min(f, 1.0))
        self.update()

    def paintEvent(self, _e) -> None:
        t = theme.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1.5, 1.5, -1.5, -1.5)
        if self._fraction is None:
            p.setPen(QPen(self._color.darker(125), 1))
            p.setBrush(self._color)
            p.drawRoundedRect(r, 4, 4)
            return
        width = r.width() * 0.22
        ring = r.adjusted(width / 2, width / 2, -width / 2, -width / 2)
        p.setPen(QPen(QColor(t.trough), width))
        p.drawEllipse(ring)
        pen = QPen(self._color, width)
        pen.setCapStyle(Qt.PenCapStyle.FlatCap)
        p.setPen(pen)
        p.drawArc(ring, 90 * 16, int(-360 * 16 * self._fraction))


def _dim_label(text: str = "") -> QLabel:
    lbl = QLabel(text)
    lbl.setProperty("dim", True)
    return lbl


class Section(QWidget):
    """A title row with a disclosure arrow; clicking it shows/hides the body."""

    def __init__(self, key: str, title: str, body: QWidget, settings: QSettings, expanded: bool = True) -> None:
        super().__init__()
        self._key = f"resources/expanded/{key}"
        self._settings = settings
        self._body = body

        self._button = QToolButton()
        self._button.setObjectName("SectionHeader")
        self._button.setText(title)
        self._button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._button.setCursor(Qt.CursorShape.PointingHandCursor)
        # No focus: a focused header makes the scroll area jump to it when the tab opens.
        self._button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._button.clicked.connect(self.toggle)
        self.summary = _dim_label()

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.addWidget(self._button)
        head.addStretch(1)
        head.addWidget(self.summary)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)
        lay.addLayout(head)
        lay.addWidget(body)

        self._set_expanded(settings.value(self._key, expanded, type=bool))

    def toggle(self) -> None:
        self._set_expanded(not self._body.isVisible())
        self._settings.setValue(self._key, self._body.isVisible())

    def _set_expanded(self, on: bool) -> None:
        self._body.setVisible(on)
        self._button.setArrowType(Qt.ArrowType.DownArrow if on else Qt.ArrowType.RightArrow)


class _LegendItem(QWidget):
    """Swatch + title + value lines, e.g. 'Receiving / 1.2 MB/s / Total Received 3.4 GB'."""

    def __init__(self, swatch: Swatch, title: str, lines: int = 1) -> None:
        super().__init__()
        self.swatch = swatch
        title_lbl = QLabel(title)
        self.values = [_dim_label() for _ in range(lines)]
        col = QVBoxLayout()
        col.setSpacing(1)
        col.setContentsMargins(0, 0, 0, 0)
        col.addWidget(title_lbl)
        for v in self.values:
            col.addWidget(v)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        row.addWidget(swatch, 0, Qt.AlignmentFlag.AlignTop)
        row.addLayout(col)
        row.addStretch(1)


class _CpuLegend(QWidget):
    def __init__(self, ncpu: int) -> None:
        super().__init__()
        grid = QGridLayout(self)
        grid.setContentsMargins(0, 4, 0, 0)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(4)
        cols = 4 if ncpu <= 24 else 8
        self._values: list[QLabel] = []
        for i in range(ncpu):
            r, c = divmod(i, cols)
            value = QLabel("0.0%")
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            value.setMinimumWidth(value.fontMetrics().horizontalAdvance("100.0%") + 4)
            grid.addWidget(Swatch(theme.cpu_color(i)), r, c * 4)
            grid.addWidget(QLabel(f"CPU{i + 1}"), r, c * 4 + 1)
            grid.addWidget(value, r, c * 4 + 2)
            self._values.append(value)
        for c in range(cols):
            grid.setColumnStretch(c * 4 + 3, 1)  # breathing room between legend columns
            grid.setColumnMinimumWidth(c * 4 + 3, 16)

    def set_values(self, per_cpu: list[float]) -> None:
        for lbl, v in zip(self._values, per_cpu):
            lbl.setText(fmt.percent(v))


def _rate_axis(v: float) -> str:
    return fmt.rate(v) if v >= 1000 else f"{v:.0f} B/s"


class ResourcesPage(QScrollArea):
    def __init__(self, ncpu: int, settings: QSettings) -> None:
        super().__init__()
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._ncpu = ncpu
        self._settings = settings
        self.gpu: Section | None = None  # built on the first sample that reports GPUs

        body = QWidget()
        self._layout = lay = QVBoxLayout(body)
        lay.setContentsMargins(24, 16, 24, 20)
        lay.setSpacing(14)

        # CPU
        self.cpu_graph = HistoryGraph(lambda: [theme.cpu_color(i) for i in range(ncpu)], stacked=True)
        self.cpu_legend = _CpuLegend(ncpu)
        self.cpu = Section("cpu", "CPU", self._stack(self.cpu_graph, self.cpu_legend), settings)

        # Memory and swap
        self.mem_graph = HistoryGraph(lambda: [QColor(theme.MEMORY_COLOR), QColor(theme.SWAP_COLOR)])
        self.mem_item = _LegendItem(Swatch(QColor(theme.MEMORY_COLOR), 36, 0.0), "Memory", 2)
        self.swap_item = _LegendItem(Swatch(QColor(theme.SWAP_COLOR), 36, 0.0), "Swap (page file)", 2)
        self.mem = Section("memory", "Memory and Swap", self._stack(self.mem_graph, self._pair(self.mem_item, self.swap_item)), settings)

        # Network
        self.net_graph = HistoryGraph(
            lambda: [QColor(theme.NET_RX_COLOR), QColor(theme.NET_TX_COLOR)],
            fixed_max=None, min_max=10_000, y_format=_rate_axis, label_sample="999.9 MB/s",
        )
        self.rx_item = _LegendItem(Swatch(QColor(theme.NET_RX_COLOR)), "Receiving", 2)
        self.tx_item = _LegendItem(Swatch(QColor(theme.NET_TX_COLOR)), "Sending", 2)
        self.net = Section("network", "Network", self._stack(self.net_graph, self._pair(self.rx_item, self.tx_item)), settings)

        # Disk
        self.disk_graph = HistoryGraph(
            lambda: [QColor(theme.DISK_READ_COLOR), QColor(theme.DISK_WRITE_COLOR)],
            fixed_max=None, min_max=100_000, y_format=_rate_axis, label_sample="999.9 MB/s",
        )
        self.read_item = _LegendItem(Swatch(QColor(theme.DISK_READ_COLOR)), "Reading", 2)
        self.write_item = _LegendItem(Swatch(QColor(theme.DISK_WRITE_COLOR)), "Writing", 2)
        self.disk = Section("disk", "Disk", self._stack(self.disk_graph, self._pair(self.read_item, self.write_item)), settings)

        for s in (self.cpu, self.mem, self.net, self.disk):
            lay.addWidget(s)
        lay.addStretch(1)
        self.setWidget(body)

    def _build_gpu(self, gpus: list[GpuInfo]) -> None:
        colors = lambda: [theme.gpu_color(i) for i in range(len(gpus))]  # noqa: E731
        self.gpu_graph = HistoryGraph(colors, label_sample="999.9 MB")  # same plot width as memory graph
        # Memory in use = dedicated VRAM + system RAM borrowed as shared memory. An integrated GPU
        # has (almost) no dedicated memory, so plotting only VRAM would show it as always empty.
        self.gpu_mem_graph = HistoryGraph(
            colors, fixed_max=None, min_max=256 * 1000**2, y_format=_size_axis, label_sample="999.9 MB"
        )
        self.gpu_items = [_LegendItem(Swatch(theme.gpu_color(i)), g.name, 3) for i, g in enumerate(gpus)]
        legend = QWidget()
        grid = QGridLayout(legend)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(24)
        grid.setVerticalSpacing(10)
        for i, item in enumerate(self.gpu_items):
            grid.addWidget(item, i // 2, i % 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        body = self._stack(
            _caption("Usage"), self.gpu_graph, _caption("Memory (dedicated + shared)"), self.gpu_mem_graph, legend
        )
        self.gpu = Section("gpu", "GPU", body, self._settings)
        self._layout.insertWidget(self._layout.count() - 1, self.gpu)  # before the trailing stretch

    @staticmethod
    def _stack(*widgets: QWidget) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(22, 0, 0, 6)
        lay.setSpacing(10)
        for x in widgets:
            lay.addWidget(x)
        return w

    @staticmethod
    def _pair(a: QWidget, b: QWidget) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(24)
        lay.addWidget(a, 1)
        lay.addWidget(b, 1)
        w.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        return w

    def update_snapshot(self, snap: Snapshot) -> None:
        s = snap.system
        n = max(len(s.per_cpu), 1)

        # Stacked layers are each core's share of the whole machine, so the top edge = total CPU.
        self.cpu_graph.add(snap.time, [v / n for v in s.per_cpu])
        self.cpu_legend.set_values(s.per_cpu)
        self.cpu.summary.setText(fmt.percent(s.cpu_total))

        mem_pct = s.mem_used / s.mem_total * 100 if s.mem_total else 0.0
        swap_pct = s.swap_used / s.swap_total * 100 if s.swap_total else 0.0
        self.mem_graph.add(snap.time, [mem_pct, swap_pct])
        self.mem_item.swatch.set_fraction(mem_pct / 100)
        self.mem_item.values[0].setText(f"{fmt.size(s.mem_used)} ({fmt.percent(mem_pct)})")
        self.mem_item.values[1].setText(f"of {fmt.size(s.mem_total)}")
        self.swap_item.swatch.set_fraction(swap_pct / 100)
        if s.swap_total:
            self.swap_item.values[0].setText(f"{fmt.size(s.swap_used)} ({fmt.percent(swap_pct)})")
            self.swap_item.values[1].setText(f"of {fmt.size(s.swap_total)}")
        else:
            self.swap_item.values[0].setText("Not available")
        self.mem.summary.setText(f"{fmt.percent(mem_pct, 0)} memory")

        self.net_graph.add(snap.time, [s.net_recv_rate, s.net_sent_rate])
        self.rx_item.values[0].setText(fmt.rate(s.net_recv_rate))
        self.rx_item.values[1].setText(f"Total Received  {fmt.size(s.net_recv_total)}")
        self.tx_item.values[0].setText(fmt.rate(s.net_sent_rate))
        self.tx_item.values[1].setText(f"Total Sent  {fmt.size(s.net_sent_total)}")
        self.net.summary.setText(f"↓ {fmt.rate(s.net_recv_rate)}   ↑ {fmt.rate(s.net_sent_rate)}")

        self.disk_graph.add(snap.time, [s.disk_read_rate, s.disk_write_rate])
        self.read_item.values[0].setText(fmt.rate(s.disk_read_rate))
        self.read_item.values[1].setText(f"Total Read  {fmt.size(s.disk_read_total)}")
        self.write_item.values[0].setText(fmt.rate(s.disk_write_rate))
        self.write_item.values[1].setText(f"Total Written  {fmt.size(s.disk_write_total)}")
        self.disk.summary.setText(f"R {fmt.rate(s.disk_read_rate)}   W {fmt.rate(s.disk_write_rate)}")

        if s.gpus:
            if self.gpu is None:
                self._build_gpu(s.gpus)
            assert self.gpu is not None
            self.gpu_graph.add(snap.time, [g.usage for g in s.gpus])
            self.gpu_mem_graph.add(snap.time, [g.memory_used for g in s.gpus])
            for item, g in zip(self.gpu_items, s.gpus):
                item.values[0].setText(f"{fmt.percent(g.usage)} usage   ·   {fmt.size(g.memory_used)} memory")
                item.values[1].setText(f"Dedicated  {fmt.size(g.dedicated_used)} of {fmt.size(g.dedicated_total)}")
                item.values[2].setText(f"Shared  {fmt.size(g.shared_used)} of {fmt.size(g.shared_total)}")
            self.gpu.summary.setText("   ".join(f"{_vendor(g.name)} {fmt.percent(g.usage, 0)}" for g in s.gpus))


def _size_axis(v: float) -> str:
    return fmt.size(v) if v >= 1000 else f"{v:.0f} B"


def _caption(text: str) -> QLabel:
    lbl = _dim_label(text)
    lbl.setContentsMargins(0, 4, 0, 0)
    return lbl


def _vendor(name: str) -> str:
    """'NVIDIA GeForce RTX 5060 Laptop GPU' -> 'NVIDIA', 'Intel(R) UHD Graphics' -> 'Intel'."""
    return name.split()[0].replace("(R)", "").replace("(TM)", "") if name else "GPU"

