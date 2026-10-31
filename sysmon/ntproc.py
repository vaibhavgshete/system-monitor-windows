"""Fast whole-system process snapshot on Windows via NtQuerySystemInformation.

This is what Task Manager uses: one call returns CPU times, memory and I/O counters for every
process, without opening any process handle — so it is fast and never hits AccessDenied.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from dataclasses import dataclass

AVAILABLE = sys.platform == "win32" and ctypes.sizeof(ctypes.c_void_p) == 8

_SystemProcessInformation = 5
_STATUS_INFO_LENGTH_MISMATCH = 0xC0000004


class _UnicodeString(ctypes.Structure):
    _fields_ = [("Length", wintypes.USHORT), ("MaximumLength", wintypes.USHORT), ("Buffer", ctypes.c_void_p)]


class _SystemProcessInfo(ctypes.Structure):
    _fields_ = [
        ("NextEntryOffset", wintypes.ULONG),
        ("NumberOfThreads", wintypes.ULONG),
        ("WorkingSetPrivateSize", ctypes.c_longlong),
        ("HardFaultCount", wintypes.ULONG),
        ("NumberOfThreadsHighWatermark", wintypes.ULONG),
        ("CycleTime", ctypes.c_ulonglong),
        ("CreateTime", ctypes.c_longlong),
        ("UserTime", ctypes.c_longlong),
        ("KernelTime", ctypes.c_longlong),
        ("ImageName", _UnicodeString),
        ("BasePriority", ctypes.c_long),
        ("UniqueProcessId", ctypes.c_void_p),
        ("InheritedFromUniqueProcessId", ctypes.c_void_p),
        ("HandleCount", wintypes.ULONG),
        ("SessionId", wintypes.ULONG),
        ("UniqueProcessKey", ctypes.c_void_p),
        ("PeakVirtualSize", ctypes.c_size_t),
        ("VirtualSize", ctypes.c_size_t),
        ("PageFaultCount", wintypes.ULONG),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
        ("PrivatePageCount", ctypes.c_size_t),
        ("ReadOperationCount", ctypes.c_longlong),
        ("WriteOperationCount", ctypes.c_longlong),
        ("OtherOperationCount", ctypes.c_longlong),
        ("ReadTransferCount", ctypes.c_longlong),
        ("WriteTransferCount", ctypes.c_longlong),
        ("OtherTransferCount", ctypes.c_longlong),
    ]


@dataclass(slots=True)
class RawProc:
    pid: int
    ppid: int
    name: str
    cpu_time: int  # user + kernel, in 100 ns units
    create_time: int
    private_ws: int  # private working set, bytes (Task Manager's "Memory")
    read_bytes: int
    write_bytes: int
    base_priority: int
    threads: int
    handles: int
    session: int


_buffer = ctypes.create_string_buffer(1 << 20)


def snapshot() -> list[RawProc]:
    """All processes, including the idle process (pid 0)."""
    global _buffer
    ntdll = ctypes.windll.ntdll
    needed = wintypes.ULONG(0)
    while True:
        status = ntdll.NtQuerySystemInformation(
            _SystemProcessInformation, _buffer, len(_buffer), ctypes.byref(needed)
        ) & 0xFFFFFFFF
        if status == _STATUS_INFO_LENGTH_MISMATCH:
            _buffer = ctypes.create_string_buffer(max(needed.value, len(_buffer)) * 2)
            continue
        if status != 0:
            raise OSError(f"NtQuerySystemInformation failed: 0x{status:08X}")
        break

    procs: list[RawProc] = []
    base = ctypes.addressof(_buffer)
    offset = 0
    while True:
        e = _SystemProcessInfo.from_address(base + offset)
        pid = e.UniqueProcessId or 0
        if e.ImageName.Buffer and e.ImageName.Length:
            name = ctypes.wstring_at(e.ImageName.Buffer, e.ImageName.Length // 2)
        else:
            name = "System Idle Process" if pid == 0 else ""
        procs.append(
            RawProc(
                pid=pid,
                ppid=e.InheritedFromUniqueProcessId or 0,
                name=name,
                cpu_time=e.UserTime + e.KernelTime,
                create_time=e.CreateTime,
                private_ws=e.WorkingSetPrivateSize,
                read_bytes=e.ReadTransferCount,
                write_bytes=e.WriteTransferCount,
                base_priority=e.BasePriority,
                threads=e.NumberOfThreads,
                handles=e.HandleCount,
                session=e.SessionId,
            )
        )
        if not e.NextEntryOffset:
            break
        offset += e.NextEntryOffset
    return procs


class _WtsProcessInfoEx(ctypes.Structure):
    _fields_ = [
        ("SessionId", wintypes.DWORD),
        ("ProcessId", wintypes.DWORD),
        ("pProcessName", wintypes.LPWSTR),
        ("pUserSid", ctypes.c_void_p),
        ("NumberOfThreads", wintypes.DWORD),
        ("HandleCount", wintypes.DWORD),
        ("PagefileUsage", wintypes.DWORD),
        ("PeakPagefileUsage", wintypes.DWORD),
        ("WorkingSetSize", wintypes.DWORD),
        ("PeakWorkingSetSize", wintypes.DWORD),
        ("UserTime", ctypes.c_longlong),
        ("KernelTime", ctypes.c_longlong),
    ]


_sid_names: dict[bytes, str | None] = {}


def _account_name(psid: int) -> str | None:
    advapi = ctypes.windll.advapi32
    key = ctypes.string_at(psid, advapi.GetLengthSid(ctypes.c_void_p(psid)))
    if key in _sid_names:
        return _sid_names[key]
    name = ctypes.create_unicode_buffer(256)
    domain = ctypes.create_unicode_buffer(256)
    n, d, use = wintypes.DWORD(256), wintypes.DWORD(256), wintypes.DWORD()
    ok = advapi.LookupAccountSidW(None, ctypes.c_void_p(psid), name, ctypes.byref(n), domain, ctypes.byref(d), ctypes.byref(use))
    result = (f"{domain.value}\\{name.value}" if domain.value else name.value) if ok else None
    _sid_names[key] = result
    return result


def process_users() -> dict[int, str]:
    """pid -> 'DOMAIN\\user' for every process, without opening any process (no admin needed)."""
    wts = ctypes.windll.wtsapi32
    level = wintypes.DWORD(1)
    info = ctypes.POINTER(_WtsProcessInfoEx)()
    count = wintypes.DWORD()
    WTS_ANY_SESSION = 0xFFFFFFFE
    if not wts.WTSEnumerateProcessesExW(None, ctypes.byref(level), wintypes.DWORD(WTS_ANY_SESSION), ctypes.byref(info), ctypes.byref(count)):
        return {}
    try:
        users: dict[int, str] = {}
        for i in range(count.value):
            e = info[i]
            if e.pUserSid:
                name = _account_name(e.pUserSid)
                if name:
                    users[e.ProcessId] = name
        return users
    finally:
        wts.WTSFreeMemoryExW(1, info, count)  # 1 = WTSTypeProcessInfoLevel1
