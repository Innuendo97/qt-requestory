"""The UI<->core boundary: ui/contracts.py Protocols, core/facade.py, tests/fakes/fake_core.py.

Six UI tasks are written against the Protocols and the fakes without seeing the
real core, so two things must hold and are asserted here:

1. the real facade services and the in-memory fakes BOTH satisfy every Protocol,
   with the very same method signatures (a UI call site that works against the
   fake works against the real thing, with no adapter in the UI);
2. the facade behaves the way the UI assumes (self-healing ``read_body``,
   normalised task status, ``EnvStatus`` numbers, reachability).

Nothing here imports Qt: contracts and fakes must be usable without a QApplication.
"""
from __future__ import annotations

import dataclasses
import inspect
import re
from datetime import date, datetime
from pathlib import Path

import pytest

from qtrequestory import __version__
from qtrequestory.core import facade
from qtrequestory.core.config import Config, Environment, default_config, save_config
from qtrequestory.core.events import (
    CancelToken,
    CollectingSink,
    EnvFinished,
    EnvSkipped,
    EnvStarted,
    FileDone,
    FileFailed,
    FileProgress,
    FileStarted,
    IndexFileScanned,
    IndexFinished,
    IndexStarted,
    LogMessage,
    RemoteIndexRead,
    SyncFinished,
    SyncStarted,
)
from qtrequestory.core.index.builder import IndexBuilder
from qtrequestory.core.index.db import open_index
from qtrequestory.core.index.search import IndexStale, SearchQuery, read_body as core_read_body
from qtrequestory.core.paths import AppPaths
from qtrequestory.core.scheduler import TASK_NAME, TaskStatus
from qtrequestory.ui import contracts
from qtrequestory.ui.contracts import (
    ArchiveApi,
    ConfigApi,
    CoreServices,
    EnvStatus,
    ExtractApi,
    IndexApi,
    OfficinaApi,
    SchedulerApi,
    SyncApi,
)
from tests.fakes import fake_core

from .conftest import FDI_A, FDI_B, KEY_CTE, KEY_SINT, StubServer, autoindex_html, entry_name, make_daily_file, synthetic_body

D18, D16 = date(2026, 9, 18), date(2026, 9, 16)

PROTOCOLS = (ConfigApi, SyncApi, SchedulerApi, IndexApi, ExtractApi, ArchiveApi, OfficinaApi)


# ---------------------------------------------------------------- helpers ---

def _config(tmp_path: Path, **kw) -> Config:
    return dataclasses.replace(
        default_config(),
        mirror_root=tmp_path / "mirror",
        environments=[Environment("svil", "https://example.invalid/svil/"),
                      Environment("coll", "https://example.invalid/coll/")],
        output_dir=tmp_path / "out",
        **kw,
    )


@pytest.fixture
def paths(tmp_path: Path) -> AppPaths:
    return AppPaths(tmp_path / "apphome").ensure()


@pytest.fixture
def real_services(paths: AppPaths, tmp_path: Path) -> CoreServices:
    cfg = _config(tmp_path)
    save_config(cfg, paths.config_file)
    return CoreServices.real(paths)


@pytest.fixture
def fake_services(tmp_path: Path) -> CoreServices:
    return fake_core.build_fake_core(tmp_path / "fake")


def _members(proto: type) -> list[str]:
    """Every method a Protocol declares (``__protocol_attrs__`` is what
    ``isinstance`` on a runtime_checkable Protocol looks at)."""
    names = sorted(proto.__protocol_attrs__)
    assert names, f"{proto.__name__} declares nothing"
    return names


def _params(fn) -> list[tuple[str, object, object]]:
    sig = inspect.signature(fn)
    return [(p.name, p.kind, p.default) for p in sig.parameters.values() if p.name != "self"]


# ------------------------------------------------------- no Qt in contracts ---

def test_contracts_and_fakes_do_not_import_qt():
    """UI tasks build the fake core in plain unit tests, without a QApplication,
    so neither the contracts nor the fakes may pull Qt in."""
    forbidden = re.compile(r"^\s*(from|import)\s+(PySide6|PyQt\d|shiboken6)", re.M)
    for module in (contracts, facade, fake_core):
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert not forbidden.search(source), module.__name__


# ------------------------------------------------------ protocol conformance ---

@pytest.mark.parametrize("proto", PROTOCOLS)
def test_real_and_fake_services_satisfy_the_protocols(proto, real_services: CoreServices, fake_services: CoreServices):
    attr = {ConfigApi: "config", SyncApi: "sync", SchedulerApi: "scheduler",
            IndexApi: "index", ExtractApi: "extract", ArchiveApi: "archive",
            OfficinaApi: "officina"}[proto]
    real, fake = getattr(real_services, attr), getattr(fake_services, attr)
    assert isinstance(real, proto), f"{type(real).__name__} does not satisfy {proto.__name__}"
    assert isinstance(fake, proto), f"{type(fake).__name__} does not satisfy {proto.__name__}"


@pytest.mark.parametrize("proto", PROTOCOLS)
def test_signatures_match_the_protocol_exactly(proto, real_services: CoreServices, fake_services: CoreServices):
    """Same parameter names, kinds and defaults everywhere: a UI call site written
    against the fake cannot break when the real object is plugged in."""
    attr = {ConfigApi: "config", SyncApi: "sync", SchedulerApi: "scheduler",
            IndexApi: "index", ExtractApi: "extract", ArchiveApi: "archive",
            OfficinaApi: "officina"}[proto]
    for name in _members(proto):
        expected = _params(getattr(proto, name))
        for impl in (getattr(real_services, attr), getattr(fake_services, attr)):
            assert hasattr(impl, name), f"{type(impl).__name__} misses {proto.__name__}.{name}"
            assert _params(getattr(impl, name)) == expected, f"{type(impl).__name__}.{name}"


# ------------------------------------------------ behavioural conformance ---

class TestUnknownEnvironmentConformance:
    """Where the fake stopped being a faithful stand-in, and what it cost.

    ``FakeSyncApi.check_reachable`` used to answer ``True`` for any name it had
    never been told about, while the real service answered ``False`` for an
    environment the saved configuration did not know. Every UI test therefore
    saw a green "raggiungibile" where the shipped application said the
    opposite, and the first-run wizard reported every environment unreachable
    without a single test going red.

    Signature conformance cannot catch that, so the divergence is pinned here,
    on the one question both implementations must answer the same way: an
    environment nobody has configured, pointing nowhere.
    """

    #: A port nothing listens on: the real probe fails immediately, no timeout.
    UNKNOWN = Environment("ignoto", "http://127.0.0.1:1/AutoDeploy/Input/")

    def test_both_refuse_an_environment_the_configuration_does_not_know(
        self, real_services: CoreServices, fake_services: CoreServices
    ):
        for sync in (real_services.sync, fake_services.sync):
            assert sync.check_reachable(self.UNKNOWN, timeout=1.0) is False, type(sync).__name__

    def test_both_answer_without_raising_and_without_consulting_the_config(
        self, real_services: CoreServices, fake_services: CoreServices
    ):
        """The contract promises the probe never raises — not even for a name
        that has no entry anywhere — because it runs from a worker whose only
        error path is a status line."""
        for sync in (real_services.sync, fake_services.sync):
            assert isinstance(sync.check_reachable(self.UNKNOWN, timeout=1.0), bool)

    def test_env_status_of_an_unknown_environment_agrees_too(
        self, real_services: CoreServices, fake_services: CoreServices
    ):
        """The other method the wizard calls with a name nothing has saved: it
        must describe an empty mirror, not explode."""
        for sync in (real_services.sync, fake_services.sync):
            status = sync.env_status(self.UNKNOWN.name)
            assert (status.env, status.last_success, status.n_local_files) == ("ignoto", None, 0)


def test_contracts_reexport_the_real_core_dataclasses():
    """The UI must never define its own copy of a core dataclass."""
    from qtrequestory.core import scheduler as sched
    from qtrequestory.core.config import Config as CoreConfig, Environment as CoreEnvironment
    from qtrequestory.core.index.builder import IndexPlan as CoreIndexPlan
    from qtrequestory.core.index.search import Coverage as CoreCoverage, SearchHit as CoreSearchHit, SearchQuery as CoreSearchQuery
    from qtrequestory.core.jobs import JobReport as CoreJobReport
    from qtrequestory.core.sync import SyncReport as CoreSyncReport

    assert contracts.Config is CoreConfig
    assert contracts.Environment is CoreEnvironment
    assert contracts.SearchQuery is CoreSearchQuery
    assert contracts.SearchHit is CoreSearchHit
    assert contracts.Coverage is CoreCoverage
    assert contracts.IndexPlan is CoreIndexPlan
    assert contracts.JobReport is CoreJobReport
    assert contracts.SyncReport is CoreSyncReport
    assert contracts.TaskStatus is sched.TaskStatus
    assert contracts.EnvStatus is facade.EnvStatus
    # The "no task" sentinel too: without it the UI (and its tests) have to
    # reach past the contract into core.scheduler to render that one state.
    assert contracts.NOT_REGISTERED is sched.NOT_REGISTERED


def test_contracts_reexport_everything_the_ui_imports():
    """One import surface: the UI never needs a second core import.

    Pure helpers (``parse_entry_name`` for the smart paste) and the event
    classes the sink delivers are re-exported next to the Protocols; only
    stateful, injectable things get a Protocol.
    """
    from qtrequestory.core import events
    from qtrequestory.core.daily import parse_entry_name as core_parse_entry_name

    assert contracts.parse_entry_name is core_parse_entry_name
    for name in ("SyncStarted", "EnvStarted", "EnvSkipped", "EnvUnreachable", "RemoteIndexRead",
                 "FileSkipped", "FileStarted", "FileProgress", "FileDone", "FileFailed",
                 "EnvFinished", "SyncFinished", "IndexStarted", "IndexFileScanned",
                 "IndexFinished", "LogMessage", "CancelToken", "Cancelled", "EventSink"):
        assert getattr(contracts, name) is getattr(events, name), name
    missing = [n for n in contracts.__all__ if not hasattr(contracts, n)]
    assert missing == []


def test_core_services_misc_accessors(real_services: CoreServices, fake_services: CoreServices, paths: AppPaths):
    assert real_services.version() == __version__
    assert real_services.app_log_path() == paths.app_log
    assert real_services.sync_log_path() == paths.sync_log
    assert real_services.index_db_path() == real_services.config.load().index_path
    for s in (real_services, fake_services):
        assert isinstance(s.version(), str)
        assert isinstance(s.app_log_path(), Path)
        assert isinstance(s.index_db_path(), Path)
        assert isinstance(s.paths, AppPaths)


# ------------------------------------------------------------ config facade ---

class TestConfigService:
    def test_first_run_then_load_and_save(self, tmp_path: Path):
        paths = AppPaths(tmp_path / "apphome").ensure()
        svc = facade.ConfigService(paths)
        assert svc.is_first_run() is True
        assert svc.config_path() == paths.config_file
        cfg = svc.load()  # the defaults, and still no file: the wizard must run
        assert svc.is_first_run() is True
        updated = dataclasses.replace(cfg, default_window_days=7)
        svc.save(updated)
        assert svc.is_first_run() is False
        assert facade.ConfigService(paths).load().default_window_days == 7
        # the saved config is what the other services see from now on
        assert svc.current().default_window_days == 7

    def test_validate_and_import(self, tmp_path: Path):
        paths = AppPaths(tmp_path / "apphome").ensure()
        svc = facade.ConfigService(paths)
        bad = dataclasses.replace(svc.load(), environments=[Environment("sv il", "ftp://x")])
        assert len(svc.validate(bad)) >= 2
        assert svc.validate(dataclasses.replace(svc.load(), environments=[])) == []
        sidecar = tmp_path / "environments.json"
        sidecar.write_text('[{"name": "coll", "url": "https://example.invalid/coll/"}]', encoding="utf-8")
        assert svc.import_environments_file(sidecar) == [Environment("coll", "https://example.invalid/coll/")]
        assert svc.find_sidecar_environments() is None
        svc = facade.ConfigService(paths, exe_dir=tmp_path)
        assert svc.find_sidecar_environments() == sidecar

    def test_detect_editor_is_injectable(self, tmp_path: Path):
        editor = tmp_path / "notepad++.exe"
        editor.write_bytes(b"MZ")
        svc = facade.ConfigService(AppPaths(tmp_path / "apphome").ensure(), editor_candidates=[editor])
        assert svc.detect_editor() == editor


# -------------------------------------------------------------- sync facade ---

class TestEnvStatus:
    def test_env_status_on_the_mirror_with_a_state_file(self, mirror, tmp_path: Path, fake_clock):
        cfg = dataclasses.replace(_config(tmp_path), mirror_root=mirror.root)
        state_file = cfg.state_path
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(
            '{"envs": {"coll": {"last_success": "2026-09-22T09:00:00", "last_remote_daily": 3, '
            '"last_downloaded": 2, "newest_day": "2026-09-21"}}}',
            encoding="utf-8",
        )
        svc = facade.SyncService(lambda: cfg, clock=fake_clock)

        coll = svc.env_status("coll")
        assert isinstance(coll, EnvStatus)
        assert coll.env == "coll"
        assert coll.last_success == datetime(2026, 9, 22, 9, 0)
        assert coll.never_synced is False
        assert coll.n_local_files == 3
        assert coll.local_bytes == sum(p.stat().st_size for (e, _), p in mirror.files.items() if e == "coll")
        assert coll.latest_day == D18
        assert coll.last_remote_daily == 3 and coll.last_downloaded == 2
        # nothing indexed yet -> every local file is pending
        assert coll.index_pending == 3
        assert coll.index_up_to_date is False
        # the state says 09:00 today and the clock is 09:30, before the 18:30 compaction
        assert coll.fresh is True and svc.is_fresh("coll") is True
        assert coll.freshness == "fresh" and svc.freshness("coll") == "fresh"

        svil = svc.env_status("svil")
        assert (svil.last_success, svil.never_synced, svil.fresh) == (None, True, False)
        assert (svil.n_local_files, svil.latest_day, svil.index_pending) == (1, D16, 1)

    def test_a_quiet_today_reads_empty_today_through_the_facade(self, tmp_path: Path):
        """1.1.1: the listing read at 22:33 showed today at 0 bytes and
        yesterday is mirrored: not fresh (the next run re-lists), but the card
        reads it as up to date."""
        from qtrequestory.core.state import SyncState

        cfg = _config(tmp_path)
        st = SyncState(cfg.state_path).load()
        when = datetime(2026, 9, 24, 22, 33)
        st.record_listing("svil", when, oldest_listed=date(2026, 9, 21),
                          listed_nonempty=(date(2026, 9, 23),),
                          listed_empty=(date(2026, 9, 22), date(2026, 9, 24)))
        st.mark_success("svil", when, newest_day=date(2026, 9, 23))
        svc = facade.SyncService(lambda: cfg, clock=lambda: datetime(2026, 9, 24, 22, 40))

        status = svc.env_status("svil")
        assert (status.fresh, status.freshness) == (False, "empty_today")
        assert (svc.is_fresh("svil"), svc.freshness("svil")) == (False, "empty_today")
        other = svc.env_status("coll")
        assert (other.fresh, other.freshness) == (False, "stale")

    def test_freshness_of_an_unusable_mirror_is_stale(self, tmp_path: Path):
        cfg = dataclasses.replace(_config(tmp_path), mirror_root=Path(""))
        svc = facade.SyncService(lambda: cfg)
        assert svc.freshness("svil") == "stale"
        assert svc.env_status("svil").freshness == "stale"

    def test_a_0_byte_day_is_no_traffic_not_archive_content(self, mirror, tmp_path: Path,
                                                            fake_clock):
        """``n_local_files``/``latest_day`` count the days with calls only."""
        from qtrequestory.core.daily import local_path

        cfg = dataclasses.replace(_config(tmp_path), mirror_root=mirror.root)
        quiet = local_path(mirror.root, "coll", date(2026, 9, 19))
        quiet.parent.mkdir(parents=True, exist_ok=True)
        quiet.write_bytes(b"")
        coll = facade.SyncService(lambda: cfg, clock=fake_clock).env_status("coll")
        assert (coll.n_local_files, coll.latest_day) == (3, D18)

    def test_index_pending_drops_after_indexing(self, mirror, tmp_path: Path, fake_clock):
        cfg = dataclasses.replace(_config(tmp_path), mirror_root=mirror.root)
        conn = open_index(cfg.index_path)
        IndexBuilder(conn, cfg.mirror_root, lambda ev: None).update(["coll", "svil"])
        conn.close()
        svc = facade.SyncService(lambda: cfg, clock=fake_clock)
        st = svc.env_status("coll")
        assert st.index_pending == 0
        assert st.index_up_to_date is True

    def test_env_status_of_an_empty_mirror(self, tmp_path: Path, fake_clock):
        cfg = _config(tmp_path)
        svc = facade.SyncService(lambda: cfg, clock=fake_clock)
        st = svc.env_status("svil")
        assert (st.n_local_files, st.local_bytes, st.latest_day, st.index_pending) == (0, 0, None, 0)
        assert st.index_up_to_date is True
        # refreshing the page must not create an index database as a side effect
        assert not cfg.index_path.exists()


class TestReachability:
    def test_reachable_when_the_autoindex_answers(self, tmp_path: Path, stub_server: StubServer):
        stub_server.add("/coll/", autoindex_html([("20260918.txt", "18-Sep-2026 18:30", 42)]))
        cfg = dataclasses.replace(_config(tmp_path), environments=[
            Environment("coll", stub_server.url + "/coll/"),
            Environment("svil", stub_server.url + "/missing/"),
        ])
        svc = facade.SyncService(lambda: cfg)
        assert svc.check_reachable(cfg.env("coll")) is True
        assert svc.check_reachable(cfg.env("svil"), timeout=1.0) is False

    def test_it_probes_the_environment_it_is_given_not_the_saved_one(
        self, tmp_path: Path, stub_server: StubServer
    ):
        """The first-run wizard has saved nothing yet.

        "Verifica raggiungibilita" ran before [Fine], so a probe that resolved
        the name against the stored configuration found an empty
        ``environments`` list and answered "non raggiungibile" for every row.
        The URL under the user's cursor is the only thing worth probing, so it
        is what the caller passes.
        """
        stub_server.add("/nuovo/", autoindex_html([("20260918.txt", "18-Sep-2026 18:30", 42)]))
        cfg = dataclasses.replace(_config(tmp_path), environments=[])  # nothing saved yet
        svc = facade.SyncService(lambda: cfg)
        assert svc.check_reachable(Environment("nuovo", stub_server.url + "/nuovo/")) is True

    def test_an_edited_url_is_probed_and_not_the_one_still_on_disk(
        self, tmp_path: Path, stub_server: StubServer
    ):
        """Impostazioni: the same for a URL corrected but not yet saved."""
        stub_server.add("/corretto/", autoindex_html([("20260918.txt", "18-Sep-2026 18:30", 42)]))
        cfg = dataclasses.replace(_config(tmp_path), environments=[
            Environment("coll", stub_server.url + "/sbagliato/"),
        ])
        svc = facade.SyncService(lambda: cfg)
        assert svc.check_reachable(cfg.env("coll"), timeout=1.0) is False
        edited = Environment("coll", stub_server.url + "/corretto/")
        assert svc.check_reachable(edited) is True

    def test_a_url_urllib_cannot_open_is_not_reachable(self, tmp_path: Path):
        """An environments.json imported from a colleague may hold anything.

        urllib answers a missing scheme with ``ValueError`` and an unknown one
        with ``URLError``; the Protocol promises this method never raises, so
        both end up as "not reachable" (Impostazioni shows the real reason
        through ``config.validate``).
        """
        cfg = dataclasses.replace(_config(tmp_path), environments=[
            Environment("noscheme", "example.invalid/AutoDeploy/Input/"),
            Environment("ftp", "ftp://127.0.0.1:1/AutoDeploy/Input/"),
        ])
        svc = facade.SyncService(lambda: cfg)
        assert svc.check_reachable(cfg.env("noscheme"), timeout=1.0) is False
        assert svc.check_reachable(cfg.env("ftp"), timeout=1.0) is False

    def test_a_login_page_is_not_reachable(self, tmp_path: Path, stub_server: StubServer):
        """A captive portal answers 200 with HTML that holds no log file at all;
        the core treats that as unreachable and so must the UI's check."""
        stub_server.add("/coll/", "<html><body>Please sign in</body></html>")
        cfg = dataclasses.replace(_config(tmp_path),
                                  environments=[Environment("coll", stub_server.url + "/coll/")])
        assert facade.SyncService(lambda: cfg).check_reachable(cfg.env("coll")) is False


class TestSyncMisc:
    def test_lock_holder_is_none_while_free_and_a_string_while_held(self, tmp_path: Path):
        from qtrequestory.core.lock import ProcessLock
        cfg = _config(tmp_path)
        svc = facade.SyncService(lambda: cfg)
        assert svc.lock_holder() is None
        other = ProcessLock(cfg.lock_path)
        assert other.acquire()
        try:
            holder = svc.lock_holder()
            assert isinstance(holder, str) and holder
        finally:
            other.release()
        assert svc.lock_holder() is None

    def test_lock_holder_never_takes_the_lock(self, tmp_path: Path, monkeypatch):
        """A poll that took the lock could make a scheduled run skip an hour."""
        from qtrequestory.core import lock as lock_mod
        from qtrequestory.core.lock import ProcessLock
        cfg = _config(tmp_path)
        other = ProcessLock(cfg.lock_path)
        assert other.acquire()
        try:
            monkeypatch.setattr(lock_mod, "_try_lock", lambda fd: pytest.fail("the probe took the lock"))
            monkeypatch.setattr(ProcessLock, "acquire", lambda self, blocking=False: pytest.fail("acquire"))
            assert facade.SyncService(lambda: cfg).lock_holder() is not None
        finally:
            monkeypatch.undo()
            other.release()
        assert facade.SyncService(lambda: cfg).lock_holder() is None

    def test_lock_holder_of_an_unusable_mirror_is_none(self, tmp_path: Path):
        """The page polls this on a timer: a bad path must not raise there."""
        cfg = dataclasses.replace(_config(tmp_path), mirror_root=tmp_path / "nul:" / "x")
        assert facade.SyncService(lambda: cfg).lock_holder() is None

    def test_sync_log_path_and_tail(self, tmp_path: Path, paths: AppPaths):
        paths.sync_log.write_text("\n".join(f"riga {i}" for i in range(10)) + "\n", encoding="utf-8")
        svc = facade.SyncService(lambda: _config(tmp_path), paths=paths)
        assert svc.sync_log_path() == paths.sync_log
        assert svc.tail_sync_log(3) == ["riga 7", "riga 8", "riga 9"]
        assert len(svc.tail_sync_log(100)) == 10

    def test_tail_of_a_missing_log_is_empty(self, tmp_path: Path, paths: AppPaths):
        svc = facade.SyncService(lambda: _config(tmp_path), paths=paths)
        assert svc.tail_sync_log(5) == []

    def test_run_delegates_to_the_sync_job(self, tmp_path: Path, monkeypatch, paths: AppPaths):
        cfg = _config(tmp_path)
        seen = {}

        def fake_job(config, **kw):
            seen.update(kw, config=config)
            return contracts.JobReport(sync=None, indexed_files=0, exit_code=0)

        monkeypatch.setattr(facade, "run_sync_job", fake_job)
        svc = facade.SyncService(lambda: cfg, paths=paths)
        sink, cancel = CollectingSink(), CancelToken()
        report = svc.run(["coll"], force=True, dry_run=False, sink=sink, cancel=cancel)
        assert report.exit_code == 0
        assert seen["config"] is cfg
        assert seen["envs"] == ["coll"] and seen["force"] is True and seen["dry_run"] is False
        assert seen["sink"] is sink and seen["cancel"] is cancel


# --------------------------------------------------------- scheduler facade ---

CSV_WITH_PLACEHOLDERS = (
    '"PC-01","\\qtRequestory Sync","N/D","Pronto","Solo interattivo","","267009","D\\u","C:\\x.exe --sync",'
    '"N/D","desc","Abilitato","Disabilitato","Arresta","01:00:00","x","Giornaliero","09:00:00","22/09/2026",'
    '"N/D","Ogni giorno","N/D","N/D","N/D"\r\n'
)

TASK_XML = (
    '<?xml version="1.0" encoding="UTF-16"?>'
    '<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">'
    '<Actions Context="Author"><Exec><Command>{command}</Command><Arguments>--sync</Arguments></Exec></Actions>'
    "</Task>"
)


class TestSchedulerService:
    def _runner(self, tmp_path: Path, calls: list, csv_text: str = CSV_WITH_PLACEHOLDERS, rc: int = 0,
                command: str | None = None):
        import subprocess

        xml = TASK_XML.format(command=command if command is not None else tmp_path / "qtRequestory.exe")

        def runner(args: list[str]):
            calls.append(args)
            if args[:1] == ["/Query"] and "/XML" in args:
                return subprocess.CompletedProcess(args, rc, stdout=xml, stderr="")
            if args[:1] == ["/Query"]:
                return subprocess.CompletedProcess(args, rc, stdout=csv_text, stderr="")
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

        return runner

    def _service(self, tmp_path: Path, calls: list, **kw) -> facade.SchedulerService:
        exe = tmp_path / "qtRequestory.exe"
        exe.write_bytes(b"MZ")
        return facade.SchedulerService(runner=self._runner(tmp_path, calls, **kw), exe_provider=lambda: exe)

    def test_status_normalises_placeholder_csv_fields(self, tmp_path: Path):
        calls: list = []
        st = self._service(tmp_path, calls).status()
        assert isinstance(st, TaskStatus)
        assert st.registered is True and st.exe_matches is True
        assert st.state == "Pronto"
        assert st.next_run is None   # "N/D"
        assert st.last_run is None   # ""
        assert st.last_result == 267009

    def test_status_placeholder_command_is_not_a_path(self, tmp_path: Path):
        """``Path("N/D")`` would be shown to the user as a real command."""
        calls: list = []
        exe = tmp_path / "qtRequestory.exe"
        exe.write_bytes(b"MZ")
        svc = facade.SchedulerService(
            runner=self._runner(tmp_path, calls, command="N/D"), exe_provider=lambda: exe
        )
        st = svc.status()
        assert st.registered is True
        assert st.command is None
        assert st.exe_matches is False

    def test_status_when_not_registered(self, tmp_path: Path):
        calls: list = []
        st = self._service(tmp_path, calls, rc=1).status()
        assert st.registered is False and st.command is None

    def test_register_unregister_run_now_and_legacy(self, tmp_path: Path):
        calls: list = []
        svc = self._service(tmp_path, calls)
        svc.register()
        svc.run_now()
        svc.unregister()
        assert svc.detect_legacy_task() is True  # the fake runner answers /Query with rc 0
        svc.remove_legacy_task()
        verbs = [c[0] for c in calls]
        assert verbs[:3] == ["/Create", "/Run", "/Delete"]
        assert ["/Create", "/TN", TASK_NAME] == calls[0][:3]

    def test_register_uses_the_schedule_saved_in_the_configuration(self, tmp_path: Path):
        """Impostazioni writes the block; the task must be built from it, not
        from the values ``TaskSpec`` happens to default to."""
        import subprocess
        import xml.etree.ElementTree as ET

        from qtrequestory.core.config import ScheduleSettings

        ns = "http://schemas.microsoft.com/windows/2004/02/mit/task"
        cfg = dataclasses.replace(
            default_config(),
            schedule=ScheduleSettings(start_time="07:30", repeat_every_h=2, repeat_for_h=0,
                                      run_at_logon=False),
        )
        exe = tmp_path / "qtRequestory.exe"
        exe.write_bytes(b"MZ")
        written: list[str] = []

        def runner(args: list[str]):
            if args[:1] == ["/Create"]:
                written.append(Path(args[args.index("/XML") + 1]).read_text(encoding="utf-16"))
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

        facade.SchedulerService(
            runner=runner, exe_provider=lambda: exe, config_source=lambda: cfg
        ).register()

        root = ET.fromstring(written[0].lstrip("﻿").split("?>", 1)[1])
        trigger = root.find(f"{{{ns}}}Triggers/{{{ns}}}CalendarTrigger")
        assert trigger is not None
        assert (trigger.find(f"{{{ns}}}StartBoundary").text or "").endswith("T07:30:00")
        assert trigger.find(f"{{{ns}}}Repetition") is None
        assert root.find(f"{{{ns}}}Triggers/{{{ns}}}LogonTrigger") is None

    def test_exe_path_and_unstable_location(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        calls: list = []
        svc = self._service(tmp_path, calls)
        assert svc.exe_path() == tmp_path / "qtRequestory.exe"

        # Fixed paths, independent of where %TEMP% and the home folder really
        # are (an isolated run may put USERPROFILE itself under %TEMP%).
        temp = Path("C:/FakeTemp")
        monkeypatch.setenv("TEMP", str(temp))
        monkeypatch.setenv("TMP", str(temp))
        monkeypatch.setattr("tempfile.tempdir", str(temp))

        def elsewhere(exe: Path) -> facade.SchedulerService:
            return facade.SchedulerService(runner=self._runner(tmp_path, calls), exe_provider=lambda: exe)

        assert "%TEMP%" in (elsewhere(temp / "x" / "qtRequestory.exe").unstable_location_reason() or "")
        downloads = Path("C:/Users/someone/Downloads/qtRequestory.exe")
        assert "Downloads" in (elsewhere(downloads).unstable_location_reason() or "")
        assert elsewhere(Path("C:/Tools/qtRequestory/qtRequestory.exe")).unstable_location_reason() is None

    def test_without_an_exe_nothing_can_be_registered(self, tmp_path: Path):
        calls: list = []
        svc = facade.SchedulerService(runner=self._runner(tmp_path, calls), exe_provider=lambda: None)
        assert svc.exe_path() is None
        assert svc.unstable_location_reason() is None
        with pytest.raises(facade.SchedulerError):
            svc.register()


# ------------------------------------------------------------- index facade ---

@pytest.fixture
def index_svc(mirror, tmp_path: Path):
    cfg = dataclasses.replace(_config(tmp_path), mirror_root=mirror.root)
    svc = facade.IndexService(lambda: cfg)
    svc.update(["coll", "svil"], full_rebuild=False, sink=CollectingSink(), cancel=CancelToken())
    return svc, mirror, cfg


class TestIndexService:
    def test_search_coverage_and_pickers(self, index_svc):
        svc, mirror, cfg = index_svc
        hits = svc.search(SearchQuery("coll", fdi_prefix=FDI_A))
        assert len(hits) == 4 and hits[0].day == D18
        assert svc.coverage("coll").n_files == 3
        assert svc.coverage("nope") is None
        assert KEY_SINT in svc.list_template_keys("coll")
        assert svc.list_template_keys("coll", prefix="CTR_") == [KEY_CTE]
        assert svc.count_local_files() == 4
        # the wizard asks about a folder the user just browsed to, before saving
        assert svc.count_local_files(mirror.root) == 4
        assert svc.count_local_files(cfg.mirror_root / "nope") == 0
        assert svc.db_path() == cfg.index_path
        assert svc.plan(["coll", "svil"]).to_scan == []

    def test_read_body_matches_the_file(self, index_svc):
        svc, mirror, _ = index_svc
        hit = svc.search(SearchQuery("coll", fdi_prefix=FDI_B, template_key=KEY_SINT))[0]
        assert svc.read_body(hit) == dict(mirror.entries[("coll", D18)])[hit.name]

    def test_read_body_self_heals_after_the_file_was_rewritten(self, index_svc):
        """A re-downloaded daily file shifts every offset; the UI must never see
        ``IndexStale`` — the facade rescans that day and retries once."""
        svc, mirror, _ = index_svc
        hit = svc.search(SearchQuery("coll", fdi_prefix=FDI_B, template_key=KEY_SINT))[0]
        original = svc.read_body(hit)
        path = mirror.files[("coll", D18)]
        path.write_bytes(b"### extra_ENTRY_0000000000000000.json\r\n{}\r\n" + path.read_bytes())

        with pytest.raises(IndexStale):  # the raw core call still raises...
            core_read_body(hit)
        assert svc.read_body(hit) == original  # ...the facade heals it
        # after the rescan the index agrees with the file again
        hit2 = svc.search(SearchQuery("coll", fdi_prefix=FDI_B, template_key=KEY_SINT))[0]
        assert core_read_body(hit2) == original

    def test_read_body_self_heal_picks_the_same_copy_of_a_duplicated_name(self, mirror, tmp_path: Path):
        """A replayed call leaves the same name twice in one day. After a
        rewrite (here CRLF -> LF: same order, new offsets) the second copy must
        still come back as the second copy."""
        name = entry_name(FDI_A, "MOD_TEST_A")
        # the first copy is the newer one, so search lists it first
        first = synthetic_body(FDI_A, "MOD_TEST_A", request_date="2026-09-18T09:00:00.000Z", noise=False)
        second = synthetic_body(FDI_A, "MOD_TEST_A", request_date="2026-09-18T08:00:00.000Z", noise=False)
        day = date(2026, 9, 18)
        make_daily_file(tmp_path / "m", "coll", day, [(name, first), (name, second)])
        cfg = dataclasses.replace(_config(tmp_path), mirror_root=tmp_path / "m")
        svc = facade.IndexService(lambda: cfg)
        svc.update(["coll"], full_rebuild=False, sink=CollectingSink(), cancel=CancelToken())
        hit = next(h for h in svc.search(SearchQuery("coll", fdi_prefix=FDI_A)) if h.seq == 1)
        assert svc.read_body(hit) == second
        make_daily_file(tmp_path / "m", "coll", day, [(name, first), (name, second)], crlf=False)

        with pytest.raises(IndexStale):
            core_read_body(hit)
        assert svc.read_body(hit) == second

    def test_read_body_raises_when_the_entry_is_really_gone(self, index_svc):
        svc, mirror, _ = index_svc
        hit = svc.search(SearchQuery("svil", fdi_prefix=FDI_A))[0]
        hit.file_path.unlink()
        with pytest.raises(IndexStale):
            svc.read_body(hit)  # one retry only: no infinite loop

    def test_update_reports_what_it_scanned(self, mirror, tmp_path: Path):
        cfg = dataclasses.replace(_config(tmp_path), mirror_root=mirror.root)
        svc = facade.IndexService(lambda: cfg)
        sink = CollectingSink()
        report = svc.update(["coll"], full_rebuild=False, sink=sink, cancel=CancelToken())
        assert (report.indexed_files, report.exit_code) == (3, 0)
        assert svc.plan(["coll"]).to_scan == []
        assert svc.update(["coll"], full_rebuild=True, sink=sink, cancel=CancelToken()).indexed_files == 3


# ----------------------------------------------------------- extract facade ---

class TestExtractService:
    def _svc(self, tmp_path: Path, opened: list, folders: list, cfg: Config | None = None) -> facade.ExtractService:
        # editor_candidates=[]: no Notepad++ is "found" on the machine running the tests
        return facade.ExtractService(lambda: cfg or _config(tmp_path), popen=opened.append,
                                     startfile=folders.append, editor_candidates=[])

    def test_pretty_json_output_name_and_temp_file(self, tmp_path: Path, mirror):
        cfg = dataclasses.replace(_config(tmp_path), mirror_root=mirror.root)
        index = facade.IndexService(lambda: cfg)
        index.update(["coll"], full_rebuild=False, sink=CollectingSink(), cancel=CancelToken())
        hit = index.search(SearchQuery("coll", fdi_prefix=FDI_A, template_key=KEY_SINT))[0]
        opened: list = []
        svc = facade.ExtractService(lambda: cfg, popen=opened.append, startfile=opened.append,
                                    editor_candidates=[])

        text = svc.pretty_json(index.read_body(hit))
        assert text.startswith('{\n    "documents": [')
        assert svc.output_name(hit) == f"20260918_{FDI_A}_{KEY_SINT}.json"
        assert svc.output_dir() == cfg.resolved_output_dir

        path = svc.write_temp_file(hit, text)
        assert path.parent == svc.output_dir()
        assert path.read_text(encoding="utf-8") == text
        assert path.read_bytes()[:1] == b"{"  # no BOM
        # a second extraction of the same hit does not overwrite the open file
        again = svc.write_temp_file(hit, text)
        assert again.name.endswith(f"_{hit.call_id}.json")

        target = tmp_path / "saved" / "body.json"
        svc.save_as(target, text)
        assert target.read_text(encoding="utf-8") == text

    def test_open_in_editor_and_folder_are_injectable(self, tmp_path: Path):
        opened: list = []
        folders: list = []
        svc = self._svc(tmp_path, opened, folders)
        assert svc.open_in_editor([tmp_path / "a.json"]) == "default"
        editor = tmp_path / "notepad++.exe"
        editor.write_bytes(b"MZ")
        cfg = dataclasses.replace(_config(tmp_path), editor_path=editor)
        svc2 = self._svc(tmp_path, opened, folders, cfg)
        assert svc2.open_in_editor([tmp_path / "a.json"]) == "editor"
        assert opened[-1][0] == str(editor)
        svc2.open_folder(tmp_path)
        assert folders[-1] == str(tmp_path)


# --------------------------------------------------------------- the fakes ---

class TestFakeCore:
    def test_fake_index_has_synthetic_hits_across_days_and_fdis(self, fake_services: CoreServices):
        index = fake_services.index
        all_hits = index.search(SearchQuery("coll", template_key="_", key_mode="contains"))
        assert len(all_hits) == 12
        assert len({h.day for h in all_hits}) == 3
        assert len({h.fdi for h in all_hits}) == 3
        # most recent first, like the real query
        assert [h.day for h in all_hits] == sorted((h.day for h in all_hits), reverse=True)
        assert index.coverage("coll") is not None
        assert index.coverage("nope") is None
        assert len(index.list_template_keys("coll")) >= 3
        assert index.count_local_files() == 3

    def test_fake_search_filters_like_the_real_one(self, fake_services: CoreServices):
        index = fake_services.index
        assert {h.fdi for h in index.search(SearchQuery("coll", fdi_prefix=FDI_A[:8]))} == {FDI_A}
        assert index.search(SearchQuery("coll", fdi_prefix="ffffffff")) == []
        assert all(h.template_key == KEY_SINT for h in index.search(SearchQuery("coll", template_key=KEY_SINT)))
        assert index.search(SearchQuery("svil", fdi_prefix=FDI_A)) == []
        windowed = index.search(SearchQuery("coll", fdi_prefix=FDI_A, day_from=D18, day_to=D18))
        assert windowed and all(h.day == D18 for h in windowed)
        assert len(index.search(SearchQuery("coll", template_key="_", key_mode="contains", limit=2))) == 2
        # blank fields count as absent, exactly like the real (SQL) query
        for empty in (SearchQuery("coll"), SearchQuery("coll", fdi_prefix="  ", template_key="")):
            with pytest.raises(ValueError):
                index.search(empty)

    def test_fake_read_body_returns_a_synthetic_body(self, fake_services: CoreServices):
        index, extract = fake_services.index, fake_services.extract
        hit = index.search(SearchQuery("coll", fdi_prefix=FDI_A))[0]
        body = index.read_body(hit)
        assert isinstance(body, bytes)
        assert extract.pretty_json(body).startswith('{\n    "documents": [')
        assert body == synthetic_body(hit.fdi, hit.template_key, request_date=hit.request_date, ndocs=hit.ndocs)

    def test_fake_sync_emits_the_scripted_sequence(self, fake_services: CoreServices):
        sink = CollectingSink()
        report = fake_services.sync.run(None, force=True, dry_run=False, sink=sink, cancel=CancelToken())
        assert report.exit_code == 0
        kinds = [type(e) for e in sink.events]
        assert kinds[0] is SyncStarted
        for kind in (EnvStarted, RemoteIndexRead, FileStarted, FileProgress, FileDone, EnvFinished):
            assert kind in kinds, kind
        assert len(sink.of(FileProgress)) >= 3
        progress = sink.of(FileProgress)
        assert progress[-1].done == progress[-1].size
        assert [e.result.status for e in sink.of(EnvFinished)] == ["ok", "ok"]
        assert sink.of(SyncFinished)[0].report is report.sync
        # ... and then the index phase, exactly like core.jobs.run_sync_job
        assert kinds.index(SyncFinished) < kinds.index(IndexStarted) < kinds.index(IndexFinished)
        assert report.indexed_files == len(sink.of(IndexFileScanned)) > 0
        assert any("sincronizzazione terminata" in e.text for e in sink.of(LogMessage))

    def test_fake_sync_with_the_lock_held_does_nothing(self, fake_services: CoreServices):
        """Same shape as the real job: one line, no events, exit 0, sync None."""
        sync = fake_services.sync
        sync.set_lock_holder("4321 2026-09-22T09:00:00")
        sink = CollectingSink()
        report = sync.run(None, force=True, dry_run=False, sink=sink, cancel=CancelToken())
        assert report == contracts.JobReport(sync=None, indexed_files=0, exit_code=0)
        assert len(sink.events) == 1
        assert sink.of(LogMessage)[0].text.startswith("sincronizzazione già in corso (")

    def test_fake_sync_dry_run_emits_exactly_what_the_engine_emits(self, fake_services: CoreServices):
        """The real engine never starts a transfer under dry_run, so there is no
        FileStarted/FileProgress either: the UI must not show a progress bar."""
        sink = CollectingSink()
        report = fake_services.sync.run(["coll"], force=True, dry_run=True, sink=sink, cancel=CancelToken())
        assert [type(e) for e in sink.events] == [
            SyncStarted, EnvStarted, RemoteIndexRead, EnvFinished, SyncFinished, LogMessage,
        ]
        assert report.indexed_files == 0
        assert sink.of(SyncStarted)[0].dry_run is True
        assert sink.of(EnvFinished)[0].result.status == "ok"

    def test_fake_sync_can_report_file_errors(self, fake_services: CoreServices):
        sync = fake_services.sync
        sync.set_failing("coll", 2)
        sink = CollectingSink()
        report = sync.run(["coll"], force=True, dry_run=False, sink=sink, cancel=CancelToken())
        assert report.exit_code == 1
        assert len(sink.of(FileFailed)) == 2
        result = sink.of(EnvFinished)[0].result
        assert (result.status, result.failed, result.downloaded) == ("errors", 2, 0)
        assert sink.of(FileDone) == []
        assert sink.of(IndexStarted)  # a run with file errors still indexes what arrived
        assert sync.env_status("coll").fresh is False  # the card follows the outcome

    def test_fake_sync_can_report_an_env_as_already_fresh(self, fake_services: CoreServices):
        sync = fake_services.sync
        sync.set_fresh("svil")
        assert sync.is_fresh("svil") is True
        sink = CollectingSink()
        report = sync.run(["svil"], force=False, dry_run=False, sink=sink, cancel=CancelToken())
        assert report.exit_code == 0
        assert [type(e) for e in sink.events] == [
            SyncStarted, EnvStarted, EnvSkipped, EnvFinished, SyncFinished, LogMessage,
            IndexStarted, IndexFileScanned, IndexFileScanned, IndexFinished,
        ]
        assert sink.of(EnvSkipped)[0].reason == "fresh"
        assert sink.of(EnvFinished)[0].result.status == "fresh"
        # "Sincronizza ora" is always force=True and must NOT skip
        sink2 = CollectingSink()
        sync.run(["svil"], force=True, dry_run=False, sink=sink2, cancel=CancelToken())
        assert sink2.of(EnvSkipped) == []
        assert sink2.of(FileDone)

    def test_fake_sync_honours_cancel(self, fake_services: CoreServices):
        sink = CollectingSink()
        cancel = CancelToken()

        def cancelling(ev):
            sink(ev)
            if isinstance(ev, FileProgress):
                cancel.cancel()

        report = fake_services.sync.run(None, force=True, dry_run=False, sink=cancelling, cancel=cancel)
        assert report.exit_code == 3
        assert "cancelled" in [e.result.status for e in sink.of(EnvFinished)]
        assert sink.of(SyncFinished)
        assert sink.of(IndexStarted) == []  # a cancelled sync never indexes

    def test_fake_sync_can_report_an_env_as_unreachable(self, fake_services: CoreServices):
        sync = fake_services.sync
        sync.set_unreachable("coll")
        assert sync.check_reachable(Environment("coll", "https://example.invalid/coll/")) is False
        assert sync.check_reachable(Environment("svil", "https://example.invalid/svil/")) is True
        sink = CollectingSink()
        report = sync.run(None, force=True, dry_run=False, sink=sink, cancel=CancelToken())
        assert [e.result.status for e in sink.of(EnvFinished)] == ["unreachable", "ok"]
        assert report.exit_code == 0  # one env still worked
        assert sync.env_status("coll").never_synced is False

        sync.set_unreachable("svil")
        report = sync.run(None, force=True, dry_run=False, sink=CollectingSink(), cancel=CancelToken())
        assert report.exit_code == 2  # nothing reachable, like the real SyncReport

    def test_fake_sync_status_and_log(self, fake_services: CoreServices):
        sync = fake_services.sync
        st = sync.env_status("coll")
        assert isinstance(st, EnvStatus) and st.env == "coll"
        assert isinstance(sync.is_fresh("coll"), bool)
        assert sync.lock_holder() is None
        sync.set_lock_holder("1234 2026-09-22T09:00:00")
        assert isinstance(sync.lock_holder(), str)
        assert isinstance(sync.sync_log_path(), Path)
        assert len(sync.tail_sync_log(2)) == 2

    def test_fake_index_update_and_plan(self, fake_services: CoreServices):
        from qtrequestory.core.events import IndexFileScanned, IndexFinished, IndexStarted
        index = fake_services.index
        assert index.plan(["coll"]).to_scan == []
        index.set_pending(3)
        assert len(index.plan(["coll"]).to_scan) == 3
        sink = CollectingSink()
        report = index.update(["coll"], full_rebuild=False, sink=sink, cancel=CancelToken())
        assert (report.indexed_files, report.exit_code) == (3, 0)
        assert sink.of(IndexStarted)[0].n_files_to_scan == 3
        assert [e.i for e in sink.of(IndexFileScanned)] == [1, 2, 3]
        assert sink.of(IndexFinished)
        assert index.plan(["coll"]).to_scan == []

        cancel = CancelToken()
        cancel.cancel()
        index.set_pending(2)
        assert index.update(["coll"], full_rebuild=False, sink=CollectingSink(), cancel=cancel).exit_code == 3

    def test_fake_index_read_body_of_a_vanished_entry(self, fake_services: CoreServices):
        index = fake_services.index
        hit = index.search(SearchQuery("coll", fdi_prefix=FDI_A))[0]
        index.set_missing(hit)
        with pytest.raises(contracts.IndexStale):
            index.read_body(hit)

    def test_fake_scheduler_is_settable(self, fake_services: CoreServices):
        sched = fake_services.scheduler
        assert sched.status().registered is False
        assert sched.detect_legacy_task() is False
        sched.set_legacy(True)
        assert sched.detect_legacy_task() is True
        sched.remove_legacy_task()
        assert sched.detect_legacy_task() is False
        sched.register()
        st = sched.status()
        assert st.registered is True and isinstance(st, TaskStatus)
        assert st.next_run is None or isinstance(st.next_run, str)
        sched.run_now()
        assert sched.run_now_calls == 1
        sched.unregister()
        assert sched.status().registered is False
        assert sched.exe_path() is None or isinstance(sched.exe_path(), Path)
        assert sched.unstable_location_reason() is None

    def test_fake_index_count_local_files_honours_root(self, fake_services: CoreServices, tmp_path: Path):
        """The wizard shows "Trovati N file" for the folder just browsed to."""
        index = fake_services.index
        assert index.count_local_files() == 3
        assert index.count_local_files(tmp_path / "vuota") == 0
        index.set_local_file_count(tmp_path / "piena", 48)
        assert index.count_local_files(tmp_path / "piena") == 48
        assert index.count_local_files() == 3

    def test_fake_config_import_can_fail(self, fake_services: CoreServices, tmp_path: Path):
        cfgsvc = fake_services.config
        assert cfgsvc.import_environments_file(tmp_path / "environments.json")
        cfgsvc.set_import_error("environments.json: JSON non valido")
        with pytest.raises(ValueError, match="JSON non valido"):
            cfgsvc.import_environments_file(tmp_path / "environments.json")
        cfgsvc.set_import_error(None)
        assert cfgsvc.import_environments_file(tmp_path / "environments.json")

    def test_fake_config_round_trip(self, fake_services: CoreServices):
        cfgsvc = fake_services.config
        assert cfgsvc.is_first_run() is False
        cfg = cfgsvc.load()
        assert [e.name for e in cfg.environments] == ["coll", "svil"]
        cfgsvc.save(dataclasses.replace(cfg, default_window_days=90))
        assert cfgsvc.load().default_window_days == 90
        assert cfgsvc.validate(cfg) == []
        assert isinstance(cfgsvc.config_path(), Path)
        assert cfgsvc.detect_editor() is None
        assert cfgsvc.find_sidecar_environments() is None

    def test_fake_extract_writes_to_a_temp_dir(self, fake_services: CoreServices, tmp_path: Path):
        index, extract = fake_services.index, fake_services.extract
        hit = index.search(SearchQuery("coll", fdi_prefix=FDI_A))[0]
        text = extract.pretty_json(index.read_body(hit))
        path = extract.write_temp_file(hit, text)
        assert path.is_file() and path.parent == extract.output_dir()
        assert path.read_text(encoding="utf-8") == text
        assert extract.output_name(hit).endswith(".json")
        target = tmp_path / "out" / "x.json"
        extract.save_as(target, text)
        assert target.read_text(encoding="utf-8") == text
        assert extract.open_in_editor([path]) in ("editor", "default")
        assert extract.opened == [[path]]
        extract.open_folder(path.parent)
        assert extract.folders == [path.parent]
