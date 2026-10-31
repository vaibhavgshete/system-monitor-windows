"""Human-readable formatting, GNOME style (decimal units)."""

from __future__ import annotations

_UNITS = ("kB", "MB", "GB", "TB", "PB")

NA = "N/A"


def size(n: float | None) -> str:
    """127500000 -> '127.5 MB'."""
    if n is None:
        return NA
    if n < 1000:
        return f"{int(n)} bytes"
    value = float(n)
    for unit in _UNITS:
        value /= 1000
        if value < 1000 or unit == _UNITS[-1]:
            return f"{value:.1f} {unit}"
    raise AssertionError("unreachable")


def rate(n: float | None) -> str:
    """Bytes per second -> '413.3 kB/s'."""
    if n is None:
        return NA
    return f"{size(n)}/s"


def percent(p: float | None, digits: int = 1) -> str:
    if p is None:
        return NA
    return f"{p:.{digits}f}%"


def duration(seconds: float) -> str:
    """Short duration used on graph axes: 60 -> '1 min', 50 -> '50 secs'."""
    seconds = int(round(seconds))
    if seconds >= 60 and seconds % 60 == 0:
        mins = seconds // 60
        return f"{mins} min" if mins == 1 else f"{mins} mins"
    if seconds == 1:
        return "1 sec"
    return f"{seconds} secs"
