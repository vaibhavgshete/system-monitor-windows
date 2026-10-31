import time

from sysmon import ntproc
from sysmon.graph import nice_ceiling
from sysmon.processes import ProcessModel, priority_name
from sysmon.sampler import Collector, ProcInfo


def test_collect_is_well_formed():
    c = Collector()
    first = c.collect()
    time.sleep(0.3)
    snap = c.collect()
    assert len(snap.processes) > 10
    assert len({p.pid for p in snap.processes}) == len(snap.processes)
    assert all(p.pid != 0 for p in snap.processes)
    assert all(0 <= p.cpu <= 100.5 for p in snap.processes)
    s = snap.system
    assert len(s.per_cpu) == c.ncpu
    assert 0 < s.mem_used <= s.mem_total
    assert first.disks  # the first sample always includes drives
    assert snap.disks is None  # ...then only every DISK_REFRESH seconds


def test_nt_snapshot_matches_psutil_pids():
    if not ntproc.AVAILABLE:
        return
    import psutil

    nt = {p.pid for p in ntproc.snapshot()}
    ps = set(psutil.pids())
    # Processes come and go between the two calls; the overlap must still be nearly total.
    assert len(nt & ps) >= 0.95 * len(ps)


def test_nice_ceiling():
    assert nice_ceiling(0) == 1.0
    assert nice_ceiling(7) == 8
    assert nice_ceiling(10) == 10
    assert nice_ceiling(11) == 20
    assert nice_ceiling(35_000) == 40_000


def test_priority_names():
    assert priority_name(8) == "Normal"
    assert priority_name(13) == "Very High"
    assert priority_name(24) == "Realtime"
    assert priority_name(4) == "Very Low"
    assert priority_name(None) is None


def _proc(pid, cpu=0.0, ppid=None, created=None):
    return ProcInfo(pid, f"p{pid}", None, cpu, 1, 0, 0, 0.0, 0.0, 8, None, ppid, create_time=created or pid)


def _pids(m, parent=None):
    from PySide6.QtCore import QModelIndex

    parent = parent or QModelIndex()
    return [m.proc_at(m.index(r, 0, parent)).pid for r in range(m.rowCount(parent))]


def _checked_model():
    from PySide6.QtTest import QAbstractItemModelTester

    m = ProcessModel()
    m._tester = QAbstractItemModelTester(m, QAbstractItemModelTester.FailureReportingMode.Fatal)
    return m


def test_model_updates_incrementally(qapp):
    m = _checked_model()
    m.update([_proc(1), _proc(2), _proc(3), _proc(4)])
    resets = []
    m.modelReset.connect(lambda: resets.append(1))
    m.update([_proc(1, 5.0), _proc(4), _proc(5)])
    assert _pids(m) == [1, 4, 5]
    assert m.proc_at(m.index(0, 0)).cpu == 5.0
    assert not resets  # rows were removed/inserted, never a full reset


def test_tree_mode_builds_and_rehomes(qapp):
    m = _checked_model()
    procs = [_proc(1), _proc(2, ppid=1), _proc(3, ppid=2), _proc(4, ppid=1), _proc(5, ppid=99)]
    m.set_tree(True, procs)
    assert _pids(m) == [1, 5]  # 5's parent doesn't exist -> top level
    one = m.index(0, 0)
    assert _pids(m, one) == [2, 4]
    assert _pids(m, m.index(0, 0, one)) == [3]

    # pid 2 exits: its child 3 moves to the top level; a new child 6 appears under 4.
    m.update([_proc(1), _proc(3, ppid=2), _proc(4, ppid=1), _proc(5, ppid=99), _proc(6, ppid=4)])
    assert sorted(_pids(m)) == [1, 3, 5]
    assert _pids(m, m.index(0, 0)) == [4]
    assert _pids(m, m.index(0, 0, m.index(0, 0))) == [6]

    # Back to a flat list.
    m.set_tree(False, [_proc(1), _proc(4, ppid=1)])
    assert _pids(m) == [1, 4]


def test_tree_ignores_reused_parent_pid(qapp):
    m = _checked_model()
    # pid 7 was created *after* its "child" -> the real parent is gone and 7 is a reused PID.
    m.set_tree(True, [_proc(7, created=500), _proc(8, ppid=7, created=100)])
    assert sorted(_pids(m)) == [7, 8]
