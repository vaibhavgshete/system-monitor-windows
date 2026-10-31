"""Scrolling history graph, drawn with QPainter in the GNOME System Monitor style."""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Callable, Sequence

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from . import fmt, theme


def nice_ceiling(v: float) -> float:
    """Round up to 1, 2, 4, 6 or 8 x 10^k so axis ticks land on readable values."""
    if v <= 0:
        return 1.0
    exp = 10 ** math.floor(math.log10(v))
    for m in (1, 2, 4, 6, 8, 10):
        if v <= m * exp * 1.0000001:
            return m * exp
    return 10 * exp


def _smooth_path(points: Sequence[QPointF]) -> QPainterPath:
    """Curve through the points. Control points share the endpoints' y values, so each
    segment stays between its endpoints: no overshoot, and stacked layers never cross."""
    path = QPainterPath(points[0])
    for a, b in zip(points, points[1:]):
        mx = (a.x() + b.x()) / 2
        path.cubicTo(QPointF(mx, a.y()), QPointF(mx, b.y()), b)
    return path


class HistoryGraph(QWidget):
    """Plots the last `window` seconds of one or more series.

    stacked=True draws filled areas on top of each other (CPU); otherwise lines with a light fill.
    fixed_max=None auto-scales the Y axis to the visible data (network, disk).
    """

    def __init__(
        self,
        colors: Callable[[], Sequence[QColor]],
        *,
        stacked: bool = False,
        fixed_max: float | None = 100.0,
        min_max: float = 1.0,
        y_format: Callable[[float], str] = lambda v: f"{v:.0f} %",
        label_sample: str = "100 %",
        window: float = 60.0,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._colors = colors
        self._stacked = stacked
        self._fixed_max = fixed_max
        self._min_max = min_max
        self._y_format = y_format
        self._label_sample = label_sample
        self._window = window
        self._samples: deque[tuple[float, tuple[float, ...]]] = deque()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(160)
        theme.manager.changed.connect(self.update)

    def sizeHint(self) -> QSize:
        return QSize(600, 200)

    def add(self, t: float, values: Sequence[float]) -> None:
        self._samples.append((t, tuple(values)))
        # Keep one sample beyond the left edge so the curve runs off the side smoothly.
        while len(self._samples) > 2 and t - self._samples[1][0] > self._window:
            self._samples.popleft()
        self.update()

    def clear(self) -> None:
        self._samples.clear()
        self.update()

    def _y_max(self) -> float:
        if self._fixed_max is not None:
            return self._fixed_max
        peak = 0.0
        for _, vals in self._samples:
            peak = max(peak, sum(vals) if self._stacked else max(vals, default=0.0))
        return nice_ceiling(max(peak, self._min_max))

    def paintEvent(self, _event) -> None:
        t = theme.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        font = QFont(self.font())
        font.setPointSizeF(max(font.pointSizeF() * 0.78, 7.0))
        p.setFont(font)
        fm = QFontMetrics(font)

        label_w = fm.horizontalAdvance(self._label_sample) + 10
        plot = QRectF(1.5, fm.height() / 2 + 1, self.width() - label_w - 3, self.height() - fm.height() * 1.5 - 8)
        if plot.width() < 20 or plot.height() < 20:
            return

        p.setPen(QPen(QColor(t.graph_grid), 1))
        p.setBrush(QColor(t.graph_bg))
        p.drawRect(plot)

        y_max = self._y_max()
        dim = QColor(t.dim)

        # Horizontal grid + right-hand labels.
        rows = 5 if self._fixed_max == 100.0 else 4
        for i in range(rows + 1):
            y = plot.bottom() - plot.height() * i / rows
            if 0 < i < rows:
                p.setPen(QPen(QColor(t.graph_grid), 1))
                p.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
            p.setPen(dim)
            p.drawText(
                QRectF(plot.right() + 6, y - fm.height() / 2, label_w, fm.height()),
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                self._y_format(y_max * i / rows),
            )

        # Vertical grid + time labels underneath (1 min, 50 secs, ... 10 secs).
        cols = 6
        for i in range(cols):
            x = plot.left() + plot.width() * i / cols
            if i:
                p.setPen(QPen(QColor(t.graph_grid), 1))
                p.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
            p.setPen(dim)
            p.drawText(QPointF(x + 3, plot.bottom() + fm.ascent() + 4), fmt.duration(self._window * (cols - i) / cols))

        if len(self._samples) >= 2:
            p.save()
            p.setClipRect(plot.adjusted(0.5, 0.5, -0.5, -0.5))
            self._draw_series(p, plot, y_max)
            p.restore()
        p.end()

    def _draw_series(self, p: QPainter, plot: QRectF, y_max: float) -> None:
        now = self._samples[-1][0]
        xs = [plot.right() - (now - ts) / self._window * plot.width() for ts, _ in self._samples]

        def y(v: float) -> float:
            return plot.bottom() - min(max(v / y_max, 0.0), 1.0) * plot.height()

        colors = list(self._colors())
        n = len(self._samples[0][1])

        if self._stacked:
            cums = []
            for _, vals in self._samples:
                acc, row = 0.0, []
                for v in vals:
                    acc += v
                    row.append(acc)
                cums.append(row)
            p.setPen(Qt.PenStyle.NoPen)
            # Draw the top layer first; each lower layer is painted over it from the baseline.
            for i in reversed(range(n)):
                pts = [QPointF(x, y(c[i] if i < len(c) else 0.0)) for x, c in zip(xs, cums)]
                path = _smooth_path(pts)
                path.lineTo(xs[-1], plot.bottom())
                path.lineTo(xs[0], plot.bottom())
                path.closeSubpath()
                p.setBrush(colors[i % len(colors)])
                p.drawPath(path)
            return

        for i in range(n):
            color = colors[i % len(colors)]
            pts = [QPointF(x, y(vals[i] if i < len(vals) else 0.0)) for x, (_, vals) in zip(xs, self._samples)]
            line = _smooth_path(pts)
            area = QPainterPath(line)
            area.lineTo(xs[-1], plot.bottom())
            area.lineTo(xs[0], plot.bottom())
            area.closeSubpath()
            fill = QColor(color)
            fill.setAlpha(40)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(fill)
            p.drawPath(area)
            p.setPen(QPen(color, 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawPath(line)
