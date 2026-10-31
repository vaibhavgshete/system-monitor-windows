"""Background sampling of system and process data.

`Sampler` lives on a worker QThread and emits a `Snapshot` every interval.
`Collector` does the actual work and has no Qt dependency, so it can be tested directly.
On Windows, processes come from one NtQuerySystemInformation call (see ntproc.py);
elsewhere psutil is used.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import psutil
from PySide6.QtCore import QObject, QTimer, Signal, Slot

from . import ntproc, winutil
from .gpu import GpuInfo, GpuMonitor


@dataclass(slots=True)
class ProcInfo:
    pid: int
    name: str
    user: str | None
    cpu: float  # percent of the whole machine (or of one core, see Collector.divide_cpu)
    memory: int | None  # private working set, bytes
    read_total: int | None
    write_total: int | None
    read_rate: float | None  # bytes/s
    write_rate: float | None
    priority: int | None  # Windows base priority (4 idle .. 24 realtime)
    exe: str | None
    ppid: int | None
    threads: int | None = None
    handles: int | None = None
    gpu: float | None = None  # percent of the busiest GPU engine this process uses
    create_time: int | None = None  # opaque, only compared between processes (detects PID reuse)


@dataclass(slots=True)
class SystemInfo:
    per_cpu: list[float]
    mem_used: int
    mem_total: int
    swap_used: int
    swap_total: int
    net_recv_rate: float
    net_sent_rate: float
    net_recv_total: int
    net_sent_total: int
    disk_read_rate: float
    disk_write_rate: float
    disk_read_total: int
    disk_write_total: int
    gpus: list[GpuInfo] = field(default_factory=list)

    @property
    def cpu_total(self) -> float:
        return sum(self.per_cpu) / len(self.per_cpu) if self.per_cpu else 0.0


@dataclass(slots=True)
class DiskInfo:
    device: str
    mountpoint: str
    fstype: str
    label: str
    total: int
    free: int
    used: int


@dataclass(slots=True)
class Snapshot:
    time: float  # time.monotonic()
    system: SystemInfo
    processes: list[ProcInfo] = field(default_factory=list)
    disks: list[DiskInfo] | None = None  # only filled every DISK_REFRESH seconds


DISK_REFRESH = 5.0


_PSUTIL_ATTRS = ["name", "ppid", "cpu_percent", "memory_info", "io_counters"]

# Seconds per tick spent resolving user names / exe paths of newly seen processes. These
# lookups open the process and are slow; whatever is left is picked up on following ticks.
_LOOKUP_BUDGET = 0.15


class Collector:
    """Keeps state between samples (previous counters, slow-lookup caches)."""

    def __init__(self) -> None:
        self.divide_cpu = True
        self.ncpu = psutil.cpu_count() or 1
        self._last_time: float | None = None
        self._prev_cpu: dict[int, tuple[int, int]] = {}  # pid -> (create_time, cpu_time)
        self._prev_io: dict[int, tuple[int, int]] = {}
        self._static: dict[int, tuple[str | None, str | None]] = {}  # pid -> (user, exe)
        self._prev_net = psutil.net_io_counters()
        self._prev_disk = psutil.disk_io_counters()
        self._last_disks = 0.0
        self._gpu = GpuMonitor()
        psutil.cpu_percent(percpu=True)  # prime the per-CPU baseline

    def collect(self) -> Snapshot:
        now = time.monotonic()
        dt = (now - self._last_time) if self._last_time else None
        self._last_time = now
        procs = self._processes_nt(dt) if ntproc.AVAILABLE else self._processes_psutil(dt)
        system = self._system(dt)
        gpu = self._gpu.sample()
        if gpu is not None:
            system.gpus = gpu.adapters
            for p in procs:
                p.gpu = gpu.per_process.get(p.pid, 0.0)
        disks = None
        if now - self._last_disks >= DISK_REFRESH or not self._last_disks:
            self._last_disks = now
            disks = self.disks()
        return Snapshot(now, system, procs, disks)

    @staticmethod
    def disks() -> list[DiskInfo]:
        result = []
        for part in psutil.disk_partitions(all=False):
            if not part.fstype:  # empty card reader / DVD drive
                continue
            try:
                usage = psutil.disk_usage(part.mountpoint)
            except OSError:
                continue
            result.append(
                DiskInfo(
                    device=part.device,
                    mountpoint=part.mountpoint,
                    fstype=part.fstype,
                    label=winutil.volume_label(part.mountpoint),
                    total=usage.total,
                    free=usage.free,
                    used=usage.used,
                )
            )
        return result

    # -- system --------------------------------------------------------------------------

    def _system(self, dt: float | None) -> SystemInfo:
        per_cpu = psutil.cpu_percent(percpu=True)
        vm = psutil.virtual_memory()
        try:
            sw = psutil.swap_memory()
            swap_used, swap_total = sw.used, sw.total
        except (RuntimeError, OSError):
            swap_used = swap_total = 0

        net = psutil.net_io_counters()
        disk = psutil.disk_io_counters()

        def r(cur: int, prev: int) -> float:
            return max(cur - prev, 0) / dt if dt else 0.0

        info = SystemInfo(
            per_cpu=per_cpu,
            mem_used=vm.total - vm.available,
            mem_total=vm.total,
            swap_used=swap_used,
            swap_total=swap_total,
            net_recv_rate=r(net.bytes_recv, self._prev_net.bytes_recv),
            net_sent_rate=r(net.bytes_sent, self._prev_net.bytes_sent),
            net_recv_total=net.bytes_recv,
            net_sent_total=net.bytes_sent,
            disk_read_rate=r(disk.read_bytes, self._prev_disk.read_bytes) if disk and self._prev_disk else 0.0,
            disk_write_rate=r(disk.write_bytes, self._prev_disk.write_bytes) if disk and self._prev_disk else 0.0,
            disk_read_total=disk.read_bytes if disk else 0,
            disk_write_total=disk.write_bytes if disk else 0,
        )
        self._prev_net, self._prev_disk = net, disk
        return info

    # -- processes -----------------------------------------------------------------------

    def _io_rates(
        self, pid: int, read: int, write: int, prev_io: dict[int, tuple[int, int]], dt: float | None
    ) -> tuple[float | None, float | None]:
        self._prev_io[pid] = (read, write)
        if not dt:
            return None, None
        if pid not in prev_io:
            return 0.0, 0.0
        pr, pw = prev_io[pid]
        return max(read - pr, 0) / dt, max(write - pw, 0) / dt

    def _processes_nt(self, dt: float | None) -> list[ProcInfo]:
        prev_cpu, self._prev_cpu = self._prev_cpu, {}
        prev_io, self._prev_io = self._prev_io, {}
        cpu_div = self.ncpu if self.divide_cpu else 1
        deadline = time.monotonic() + _LOOKUP_BUDGET
        result: list[ProcInfo] = []

        raw = ntproc.snapshot()
        users = ntproc.process_users() if any(r.pid not in self._static for r in raw if r.pid) else {}
        for r in raw:
            if r.pid == 0:  # "System Idle Process" just mirrors idle CPU time
                continue
            self._prev_cpu[r.pid] = (r.create_time, r.cpu_time)
            cpu = 0.0
            prev = prev_cpu.get(r.pid)
            if prev and prev[0] != r.create_time:
                # PID was reused by a new process: drop what we knew about the old one.
                self._static.pop(r.pid, None)
                prev_io.pop(r.pid, None)
            elif dt and prev:
                # cpu_time is in 100 ns units -> percent of one core
                cpu = max(r.cpu_time - prev[1], 0) / (dt * 1e7) * 100 / cpu_div

            read_rate, write_rate = self._io_rates(r.pid, r.read_bytes, r.write_bytes, prev_io, dt)
            user, exe = self._static_info(r.pid, deadline, users)
            result.append(
                ProcInfo(
                    pid=r.pid,
                    name=r.name or f"PID {r.pid}",
                    user=user,
                    cpu=cpu,
                    memory=r.private_ws,
                    read_total=r.read_bytes,
                    write_total=r.write_bytes,
                    read_rate=read_rate,
                    write_rate=write_rate,
                    priority=r.base_priority,
                    exe=exe,
                    ppid=r.ppid,
                    threads=r.threads,
                    handles=r.handles,
                    create_time=r.create_time,
                )
            )

        self._forget_gone(self._prev_cpu)
        return result

    def _processes_psutil(self, dt: float | None) -> list[ProcInfo]:
        """Portable fallback when the NT call is unavailable."""
        prev_io, self._prev_io = self._prev_io, {}
        cpu_div = self.ncpu if self.divide_cpu else 1
        deadline = time.monotonic() + _LOOKUP_BUDGET
        result: list[ProcInfo] = []
        seen: dict[int, None] = {}

        for p in psutil.process_iter(_PSUTIL_ATTRS, ad_value=None):
            if p.pid == 0:
                continue
            seen[p.pid] = None
            info = p.info
            mem, io = info.get("memory_info"), info.get("io_counters")
            read_total = write_total = read_rate = write_rate = None
            if io is not None:
                read_total, write_total = io.read_bytes, io.write_bytes
                read_rate, write_rate = self._io_rates(p.pid, read_total, write_total, prev_io, dt)
            user, exe = self._static_info(p.pid, deadline)
            result.append(
                ProcInfo(
                    pid=p.pid,
                    name=info.get("name") or f"PID {p.pid}",
                    user=user,
                    cpu=(info.get("cpu_percent") or 0.0) / cpu_div,
                    memory=mem.rss if mem is not None else None,
                    read_total=read_total,
                    write_total=write_total,
                    read_rate=read_rate,
                    write_rate=write_rate,
                    priority=None,
                    exe=exe,
                    ppid=info.get("ppid"),
                )
            )

        self._forget_gone(seen)
        return result

    def _forget_gone(self, alive: dict[int, object]) -> None:
        for pid in [pid for pid in self._static if pid not in alive]:
            del self._static[pid]

    def _static_info(
        self, pid: int, deadline: float, users: dict[int, str] | None = None
    ) -> tuple[str | None, str | None]:
        """User name and exe path never change, so look them up once, within the tick's budget.

        `users` (from ntproc.process_users) replaces the slow per-process psutil lookup on Windows.
        """
        cached = self._static.get(pid)
        if cached is not None:
            return cached
        if time.monotonic() > deadline:
            return None, None
        user = users.get(pid) if users is not None else None
        exe = None
        try:
            p = psutil.Process(pid)
            try:
                exe = p.exe() or None
            except psutil.Error:
                pass
            if users is None:
                try:
                    user = p.username()
                except psutil.Error:
                    pass
        except psutil.Error:
            pass
        self._static[pid] = (user, exe)
        return user, exe


class Sampler(QObject):
    """Runs a Collector on a timer. Move to a QThread and connect thread.started -> start."""

    sampled = Signal(object)  # Snapshot

    def __init__(self, interval_ms: int = 1000, divide_cpu: bool = True) -> None:
        super().__init__()
        self._interval = interval_ms
        self._divide_cpu = divide_cpu
        self._timer: QTimer | None = None
        self._collector: Collector | None = None

    @Slot()
    def start(self) -> None:
        self._collector = Collector()
        self._collector.divide_cpu = self._divide_cpu
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(self._interval)
        self._tick()

    @Slot()
    def stop(self) -> None:
        if self._timer is not None:
            self._timer.stop()

    @Slot(int)
    def set_interval(self, ms: int) -> None:
        self._interval = ms
        if self._timer is not None:
            self._timer.setInterval(ms)

    @Slot(bool)
    def set_divide_cpu(self, on: bool) -> None:
        self._divide_cpu = on
        if self._collector is not None:
            self._collector.divide_cpu = on

    @Slot()
    def _tick(self) -> None:
        assert self._collector is not None
        try:
            snap = self._collector.collect()
        except Exception as exc:  # keep the thread alive no matter what the OS throws at us
            print(f"sampler: {exc!r}")
            return
        self.sampled.emit(snap)
