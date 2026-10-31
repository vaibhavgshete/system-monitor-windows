"""GPU usage on Windows, computed the same way Task Manager does it.

- Utilisation comes from the PDH counter "\\GPU Engine(*)\\Utilization Percentage". Each instance is
  one (process, adapter, engine) triple, e.g. "pid_1234_luid_0x00000000_0x0000D1B6_phys_0_eng_0_engtype_3D".
  An engine's load is the sum over processes; an adapter's load is its busiest engine.
- Memory comes from "\\GPU Adapter Memory(*)\\Dedicated Usage" / "Shared Usage".
- Adapter names and dedicated memory size come from DXGI (matched by LUID).
Everything fails soft: if counters are unavailable, `GpuMonitor.available` is False.
"""

from __future__ import annotations

import ctypes
import re
import sys
from ctypes import wintypes
from dataclasses import dataclass, field

_PDH_FMT_DOUBLE = 0x00000200
_PDH_FMT_NOCAP100 = 0x00008000
_PDH_MORE_DATA = 0x800007D2

_ENGINE_RE = re.compile(r"pid_(\d+)_luid_(0x[0-9A-Fa-f]+_0x[0-9A-Fa-f]+)_phys_(\d+)_eng_(\d+)")
_LUID_RE = re.compile(r"luid_(0x[0-9A-Fa-f]+_0x[0-9A-Fa-f]+)")


@dataclass(slots=True)
class GpuInfo:
    name: str
    usage: float  # percent, busiest engine
    dedicated_used: int
    dedicated_total: int
    shared_used: int
    shared_total: int  # how much system RAM the GPU may borrow

    @property
    def memory_used(self) -> int:
        return self.dedicated_used + self.shared_used


@dataclass(slots=True)
class GpuSample:
    adapters: list[GpuInfo] = field(default_factory=list)
    per_process: dict[int, float] = field(default_factory=dict)  # pid -> percent


# --- DXGI: adapter names, dedicated memory, LUIDs ----------------------------------------------


class _GUID(ctypes.Structure):
    _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]


class _AdapterDesc1(ctypes.Structure):
    _fields_ = [
        ("Description", ctypes.c_wchar * 128),
        ("VendorId", wintypes.UINT),
        ("DeviceId", wintypes.UINT),
        ("SubSysId", wintypes.UINT),
        ("Revision", wintypes.UINT),
        ("DedicatedVideoMemory", ctypes.c_size_t),
        ("DedicatedSystemMemory", ctypes.c_size_t),
        ("SharedSystemMemory", ctypes.c_size_t),
        ("LuidLow", wintypes.DWORD),
        ("LuidHigh", wintypes.LONG),
        ("Flags", wintypes.UINT),
    ]


_IID_IDXGIFactory1 = _GUID(0x770AAE78, 0xF26F, 0x4DBA, (ctypes.c_ubyte * 8)(0xA8, 0x29, 0x25, 0x3C, 0x83, 0xD1, 0xB3, 0x87))
_DXGI_ADAPTER_FLAG_SOFTWARE = 2


def _com_call(obj: ctypes.c_void_p, index: int, argtypes: tuple, *args) -> int:
    """Call method `index` of a COM object's vtable; returns the HRESULT / ULONG as an int."""
    vtbl = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    proto = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, *argtypes)
    return proto(vtbl[index])(obj, *args)


def _dxgi_adapters() -> dict[str, tuple[str, int, int]]:
    """'0x00000000_0x0000D1B6' -> (name, dedicated bytes, shared bytes) for every hardware adapter."""
    result: dict[str, tuple[str, int, int]] = {}
    factory = ctypes.c_void_p()
    if ctypes.windll.dxgi.CreateDXGIFactory1(ctypes.byref(_IID_IDXGIFactory1), ctypes.byref(factory)) != 0:
        return result
    try:
        i = 0
        while True:
            adapter = ctypes.c_void_p()
            # IDXGIFactory1::EnumAdapters1 is vtable slot 12; returns DXGI_ERROR_NOT_FOUND at the end.
            if _com_call(factory, 12, (wintypes.UINT, ctypes.c_void_p), i, ctypes.byref(adapter)) != 0:
                break
            try:
                desc = _AdapterDesc1()
                # IDXGIAdapter1::GetDesc1 is vtable slot 10.
                ok = _com_call(adapter, 10, (ctypes.c_void_p,), ctypes.byref(desc)) == 0
                if ok and not desc.Flags & _DXGI_ADAPTER_FLAG_SOFTWARE:
                    luid = f"0x{desc.LuidHigh & 0xFFFFFFFF:08X}_0x{desc.LuidLow:08X}"
                    result[luid] = (desc.Description, desc.DedicatedVideoMemory, desc.SharedSystemMemory)
            finally:
                _com_call(adapter, 2, ())  # IUnknown::Release
            i += 1
    finally:
        _com_call(factory, 2, ())
    return result


# --- PDH counters -----------------------------------------------------------------------------


class _FmtValue(ctypes.Structure):
    _fields_ = [("CStatus", wintypes.DWORD), ("doubleValue", ctypes.c_double)]


class _FmtItem(ctypes.Structure):
    _fields_ = [("szName", wintypes.LPWSTR), ("FmtValue", _FmtValue)]


class _Counter:
    def __init__(self, query: ctypes.c_void_p, path: str) -> None:
        self.handle = ctypes.c_void_p()
        status = ctypes.windll.pdh.PdhAddEnglishCounterW(query, path, None, ctypes.byref(self.handle))
        if status != 0:
            raise OSError(f"PdhAddEnglishCounterW({path}) failed: 0x{status & 0xFFFFFFFF:08X}")

    def values(self) -> list[tuple[str, float]]:
        pdh = ctypes.windll.pdh
        size, count = wintypes.DWORD(0), wintypes.DWORD(0)
        fmt = _PDH_FMT_DOUBLE | _PDH_FMT_NOCAP100
        status = pdh.PdhGetFormattedCounterArrayW(self.handle, fmt, ctypes.byref(size), ctypes.byref(count), None)
        if status & 0xFFFFFFFF != _PDH_MORE_DATA:
            return []
        buf = ctypes.create_string_buffer(size.value)
        status = pdh.PdhGetFormattedCounterArrayW(self.handle, fmt, ctypes.byref(size), ctypes.byref(count), buf)
        if status != 0:
            return []
        items = ctypes.cast(buf, ctypes.POINTER(_FmtItem))
        return [(items[i].szName, items[i].FmtValue.doubleValue) for i in range(count.value) if items[i].FmtValue.CStatus in (0, 1)]


class GpuMonitor:
    """Create on the sampling thread and call `sample()` once per tick."""

    def __init__(self) -> None:
        self.available = False
        self._adapters: dict[str, tuple[str, int, int]] = {}
        if sys.platform != "win32":
            return
        try:
            self._adapters = _dxgi_adapters()
        except (OSError, AttributeError):
            self._adapters = {}
        try:
            self._query = ctypes.c_void_p()
            if ctypes.windll.pdh.PdhOpenQueryW(None, None, ctypes.byref(self._query)) != 0:
                return
            self._engine = _Counter(self._query, r"\GPU Engine(*)\Utilization Percentage")
            self._dedicated = _Counter(self._query, r"\GPU Adapter Memory(*)\Dedicated Usage")
            self._shared = _Counter(self._query, r"\GPU Adapter Memory(*)\Shared Usage")
            ctypes.windll.pdh.PdhCollectQueryData(self._query)  # rate counters need a first sample
        except (OSError, AttributeError):
            return
        self.available = bool(self._adapters)

    @property
    def adapter_names(self) -> list[str]:
        return [name for name, _dedicated, _shared in self._adapters.values()]

    def sample(self) -> GpuSample | None:
        if not self.available:
            return None
        if ctypes.windll.pdh.PdhCollectQueryData(self._query) != 0:
            return None

        engines: dict[tuple[str, str, str], float] = {}  # (luid, phys, eng) -> summed %
        per_proc_engine: dict[tuple[int, str, str, str], float] = {}
        for name, value in self._engine.values():
            m = _ENGINE_RE.search(name)
            if not m:
                continue
            pid, luid, phys, eng = int(m[1]), m[2].upper().replace("0X", "0x"), m[3], m[4]
            engines[(luid, phys, eng)] = engines.get((luid, phys, eng), 0.0) + value
            key = (pid, luid, phys, eng)
            per_proc_engine[key] = per_proc_engine.get(key, 0.0) + value

        per_process: dict[int, float] = {}
        for (pid, *_rest), value in per_proc_engine.items():
            per_process[pid] = min(max(per_process.get(pid, 0.0), value), 100.0)

        dedicated = self._sum_by_luid(self._dedicated.values())
        shared = self._sum_by_luid(self._shared.values())

        adapters = []
        for luid, (name, dedicated_total, shared_total) in self._adapters.items():
            usage = max((v for (l, _p, _e), v in engines.items() if l == luid), default=0.0)
            adapters.append(
                GpuInfo(
                    name=name,
                    usage=min(usage, 100.0),
                    dedicated_used=int(dedicated.get(luid, 0)),
                    dedicated_total=dedicated_total,
                    shared_used=int(shared.get(luid, 0)),
                    shared_total=shared_total,
                )
            )
        return GpuSample(adapters, per_process)

    @staticmethod
    def _sum_by_luid(values: list[tuple[str, float]]) -> dict[str, float]:
        out: dict[str, float] = {}
        for name, value in values:
            m = _LUID_RE.search(name)
            if m:
                luid = m[1].upper().replace("0X", "0x")
                out[luid] = out.get(luid, 0.0) + value
        return out
