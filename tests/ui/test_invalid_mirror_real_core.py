"""The real core behind the real window, with no usable mirror folder.

The one UI test on the REAL facade (the scheduler stays fake: no schtasks;
the HTTP client answers "unreachable": no network). ``Path("")`` resolves
against the CWD, and before 1.1.0's final review every page polled the index,
the sync state and the ``<env>/`` listings there — ``./.qtrequestory/index.sqlite``
appeared wherever the exe was started. The fake cannot catch that: it has no
disk behind it. Here the CWD is an empty folder and must stay empty.
"""
from __future__ import annotations

import dataclasses
import logging
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from qtrequestory.core import facade
from qtrequestory.core.config import default_config, save_config
from qtrequestory.core.http import HttpUnreachable
from qtrequestory.core.paths import AppPaths
from qtrequestory.ui.contracts import CoreServices, Environment
from qtrequestory.ui.main_window import MainWindow
from tests.fakes.fake_core import FakeSchedulerApi


class _Unreachable:
    def get_text(self, url: str, timeout: float) -> str:
        raise HttpUnreachable(url)

    def download(self, *args, **kwargs):
        raise HttpUnreachable("download")


def _real_core(home: Path) -> CoreServices:
    paths = AppPaths(home / "apphome").ensure()
    cfg = dataclasses.replace(
        default_config(), mirror_root=Path(""), output_dir=home / "out",
        environments=[Environment("svil", "https://example.invalid/svil/"),
                      Environment("coll", "https://example.invalid/coll/")],
    )
    save_config(cfg, paths.config_file)
    config = facade.ConfigService(paths)
    return CoreServices(
        config=config,
        sync=facade.SyncService(config.current, paths=paths, http_factory=_Unreachable),
        scheduler=FakeSchedulerApi(exe=home / "qtRequestory.exe"),
        index=facade.IndexService(config.current),
        extract=facade.ExtractService(config.current),
        archive=facade.ArchiveService(config.current),
        paths=paths,
    )


@pytest.fixture
def cwd(tmp_path: Path, monkeypatch) -> Path:
    folder = tmp_path / "cwd"
    folder.mkdir()
    monkeypatch.chdir(folder)
    return folder


def test_no_page_touches_the_cwd_without_a_mirror_folder(qtbot, runner, tmp_path: Path, cwd: Path,
                                                         caplog):
    """...and nothing fails loudly either: the Ricerca page shows the
    invalid-folder banner, never a logged traceback from a worker."""
    caplog.set_level(logging.INFO)
    services = _real_core(tmp_path / "home")
    assert services.config.mirror_root_errors(services.config.load())
    win = MainWindow(services, runner)
    qtbot.addWidget(win)
    win.show()
    for key in ("search", "sync", "settings", "about", "search"):
        win.show_page(key)
        QApplication.processEvents()
        qtbot.wait(50)
    qtbot.wait(300)

    search = win.page("search")
    assert search.mirror_banner.isVisibleTo(search)
    search.presenter.reload_template_keys("svil")
    search.presenter.refresh_index_state("svil")
    search.form.set_fdi("0123456789abcdef")
    search.run_search()
    win.page("sync").refresh_cards()
    qtbot.wait(300)

    assert list(cwd.iterdir()) == []
    assert [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR] == []
