from PySide6.QtCore import QSettings

from sysmon.app import MainWindow
from sysmon.sampler import Collector


def test_main_window_renders_all_tabs(qapp, tmp_path):
    settings = QSettings(str(tmp_path / "s.ini"), QSettings.Format.IniFormat)
    w = MainWindow(settings)
    try:
        c = Collector()
        w._on_snapshot(c.collect())  # first sample carries the drive list
        w._on_snapshot(c.collect())
        assert w.processes.proxy.rowCount() > 10
        assert w.filesystems.model().rowCount() >= 1
        for i in range(3):
            w.set_tab(i)
            assert not w.grab().isNull()
        w.processes.proxy.set_text("zzzz-no-such-process")
        assert w.processes.proxy.rowCount() == 0
    finally:
        w.close()


def test_app_icon_uses_logo(qapp):
    from sysmon import theme

    assert theme.LOGO_PATH.exists()
    icon = theme.app_icon()
    assert {s.width() for s in icon.availableSizes()} >= {16, 32, 256}
