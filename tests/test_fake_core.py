"""Fidelity of the in-memory fake (``tests/fakes/fake_core.py``) vs the engine.

Five UI tasks are written against the fake without ever seeing the real core,
so a fake that disagrees with ``core/sync.py`` does not just fail once: it
teaches every UI test a wrong expectation, and the mistake only surfaces in
production. The invariants asserted here are exactly the ones a UI test can
observe — the knobs, the freshness rule, cancellation and the dry-run counters.

``tests/test_contracts.py`` covers the Protocol conformance and the happy-path
event sequences; this module covers the edges where the fake drifted.
"""
from __future__ import annotations

import dataclasses
import os
import time as time_mod
from datetime import date, datetime
from pathlib import Path

import pytest

from qtrequestory.core import facade
from qtrequestory.core.config import UnknownEnvironment, default_config, save_config
from qtrequestory.core.daily import LocalDailyFile
from qtrequestory.core.events import (
    CancelToken,
    CollectingSink,
    EnvFinished,
    EnvSkipped,
    FileFailed,
    FileProgress,
    FileStarted,
    IndexStarted,
    RemoteIndexRead,
)
from qtrequestory.core.facade import IndexService
from qtrequestory.core.paths import AppPaths
from qtrequestory.core.scheduler import SchedulerError
from qtrequestory.ui.contracts import CoreServices, Environment
from tests.conftest import FDI_A, KEY_CTE, KEY_SINT, StubServer, autoindex_html, entry_name, make_daily_file, synthetic_body
from tests.fakes.fake_core import ENVS, FakeExtractApi, FakeSchedulerApi, _hit, build_fake_core, canned_pdf

#: An environment the fake does not know about: the wizard lets the user import
#: an environments.json with any names at all, so the knobs must cope.
UNKNOWN_ENV = "prod"


def _env(name: str) -> Environment:
    return Environment(name, f"https://example.invalid/{name}/")


@pytest.fixture
def fake(tmp_path: Path) -> CoreServices:
    return build_fake_core(tmp_path / "core")


def _run(sync, env: str, **kw):
    sink = CollectingSink()
    report = sync.run([env], sink=sink, cancel=CancelToken(), **kw)
    return sink, report


def _run_cancelling(sync, env: str, on_event: type):
    """Run ``env`` and hit "Annulla" the moment an ``on_event`` is emitted."""
    sink = CollectingSink()
    cancel = CancelToken()

    def cancelling(ev):
        sink(ev)
        if isinstance(ev, on_event):
            cancel.cancel()

    report = sync.run([env], force=True, dry_run=False, sink=cancelling, cancel=cancel)
    return sink, report


# ------------------------------------------------------- freshness agrees ---

def _assert_freshness_agrees(sync, env: str) -> None:
    """``is_fresh`` (the card's "Aggiornato" pill) and what a non-forced run
    does must never disagree — the engine skips exactly the fresh envs
    (``core/sync.py``: ``is_fresh`` -> ``EnvSkipped`` -> status ``fresh``)."""
    sink, _ = _run(sync, env, force=False, dry_run=False)
    status = sink.of(EnvFinished)[0].result.status
    if sync.is_fresh(env):
        assert [e.reason for e in sink.of(EnvSkipped)] == ["fresh"], f"{env}: fresh but not skipped"
        assert status == "fresh"
    else:
        assert sink.of(EnvSkipped) == [], f"{env}: skipped but not fresh"
        assert status != "fresh"


@pytest.mark.parametrize("env", ENVS)
def test_default_state_is_self_consistent_about_freshness(fake, env: str):
    """Straight out of ``build_fake_core``, with no knob touched at all."""
    _assert_freshness_agrees(fake.sync, env)


@pytest.mark.parametrize("env", ENVS)
def test_freshness_agrees_after_every_knob(fake, env: str):
    sync = fake.sync
    sync.set_fresh(env)
    assert sync.is_fresh(env) is True
    _assert_freshness_agrees(sync, env)
    sync.set_ok(env)
    assert sync.is_fresh(env) is False
    _assert_freshness_agrees(sync, env)


@pytest.mark.parametrize("env", ENVS)
def test_empty_today_is_not_fresh_and_still_runs(fake, env: str):
    """``set_empty_today``: the card reads up to date, but a non-forced run
    still goes (``is_fresh`` False), exactly like the engine."""
    sync = fake.sync
    sync.set_empty_today(env)
    assert sync.freshness(env) == "empty_today"
    assert sync.env_status(env).freshness == "empty_today"
    assert sync.is_fresh(env) is False
    _assert_freshness_agrees(sync, env)
    sync.set_fresh(env)
    assert (sync.freshness(env), sync.env_status(env).freshness) == ("fresh", "fresh")
    sync.set_ok(env)
    assert (sync.freshness(env), sync.env_status(env).freshness) == ("stale", "stale")


def test_freshness_follows_the_fresh_flag_of_a_patched_status(fake):
    fake.sync.set_env_status("coll", fresh=True)
    assert fake.sync.freshness("coll") == "fresh"
    fake.sync.set_env_status("coll", fresh=False)
    assert fake.sync.freshness("coll") == "stale"


# ------------------------------------------------------- unknown env knobs ---

def test_knobs_tolerate_an_env_the_fake_does_not_know(fake):
    """``env_status`` answers for any name, so the setters must too: a UI test
    built on an imported environments.json must not die in a KeyError — that
    file is read (and its rows probed/edited) before anything is saved to
    ``config.json``, so at that point the fake's own configuration genuinely
    does not know the name either.

    ``run()`` is different: like the real ``SyncEngine.run``, it validates its
    ``envs`` against the CURRENT configuration and raises ``UnknownEnvironment``
    for a name that is not in it (see ``test_fake_matches_real``), so the
    knobs below stop short of exercising it directly.
    """
    sync = fake.sync
    sync.set_unreachable(UNKNOWN_ENV)
    assert sync.check_reachable(_env(UNKNOWN_ENV)) is False
    assert sync.env_status(UNKNOWN_ENV).env == UNKNOWN_ENV
    assert sync.is_fresh(UNKNOWN_ENV) is False

    sync.set_failing(UNKNOWN_ENV, 2)
    sync.set_fresh(UNKNOWN_ENV)
    assert sync.is_fresh(UNKNOWN_ENV) is True

    sync.set_env_status(UNKNOWN_ENV, n_local_files=7)
    status = sync.env_status(UNKNOWN_ENV)
    assert (status.n_local_files, status.fresh) == (7, True)

    sync.set_ok(UNKNOWN_ENV)
    assert sync.is_fresh(UNKNOWN_ENV) is False
    # the on-demand status is kept, not rebuilt from scratch on every knob
    assert sync.env_status(UNKNOWN_ENV).n_local_files == 7

    with pytest.raises(UnknownEnvironment):
        _run(sync, UNKNOWN_ENV, force=True, dry_run=False)

    # Once the wizard actually saves the imported environment, run() works
    # exactly like it does for "coll"/"svil".
    fake.config.config = dataclasses.replace(
        fake.config.config,
        environments=[*fake.config.config.environments, Environment(UNKNOWN_ENV, "https://example.invalid/prod/")],
    )
    sink, report = _run(sync, UNKNOWN_ENV, force=True, dry_run=False)
    assert sink.of(EnvFinished)[0].result.status == "ok"
    assert report.exit_code == 0


# --------------------------------------------------- cancelling a bad run ---

def test_cancelling_a_failing_run_is_cancelled_not_errors(fake):
    """The engine checks the token before every file, so a user who hits
    "Annulla" while files are failing gets exit 3 (annullato), not exit 1."""
    sync = fake.sync
    sync.set_failing("coll", 3)
    sink, report = _run_cancelling(sync, "coll", FileFailed)
    assert sink.of(EnvFinished)[0].result.status == "cancelled"
    assert report.exit_code == 3
    assert len(sink.of(FileStarted)) == 1  # it stops at the cancel, not after all 3
    assert sink.of(IndexStarted) == []  # a cancelled sync never indexes


def test_cancelling_mid_file_stops_before_the_failure_is_reported(fake):
    """Cancelling while a file is in flight ends the env there: like the real
    engine, the interrupted transfer is not also reported as a failure."""
    sync = fake.sync
    sync.set_failing("coll", 3)
    sink, report = _run_cancelling(sync, "coll", FileStarted)
    assert sink.of(FileFailed) == []
    assert sink.of(EnvFinished)[0].result.status == "cancelled"
    assert report.exit_code == 3


@pytest.mark.parametrize(
    "failing, trigger",
    [(False, FileProgress), (True, FileStarted), (True, FileFailed)],
)
def test_a_cancelled_run_counts_only_what_it_reached(fake, failing: bool, trigger: type):
    """A cancel is an early exit from the engine's tally loop, not a completed
    pass: ``present``/``empty`` are incremented plan by plan *inside* that loop
    (``core/sync.py``), so only what was walked before the cancel is counted —
    unlike a dry run, which walks every plan. The scripted scenario is
    newest-first with the download ahead of the present/empty entries, so a
    cancel during it counts neither. ``SyncReport.summary_line`` prints these
    numbers for cancelled results too, so a wrong one would reach the UI.
    """
    sync = fake.sync
    if failing:
        sync.set_failing("coll", 3)
    sink, report = _run_cancelling(sync, "coll", trigger)
    result = sink.of(EnvFinished)[0].result
    assert result.status == "cancelled"
    assert (result.present, result.empty) == (0, 0)
    assert report.exit_code == 3


def test_a_run_cancelled_before_it_starts_counts_nothing_at_all(fake):
    """The env is announced and finished, but nothing was read: every counter
    stays at 0 (``core/sync.py``, the pre-flight cancel check)."""
    cancel = CancelToken()
    cancel.cancel()
    sink = CollectingSink()
    report = fake.sync.run(["coll"], force=True, dry_run=False, sink=sink, cancel=cancel)
    result = sink.of(EnvFinished)[0].result
    assert (result.status, result.downloaded, result.present, result.empty, result.failed) == (
        "cancelled", 0, 0, 0, 0
    )
    assert sink.of(RemoteIndexRead) == []
    assert report.exit_code == 3


# ---------------------------------------------------------- dry-run counts ---

def test_dry_run_result_carries_the_counts_it_announced(fake):
    """The engine counts present/empty before the ``if dry_run`` branch, so a
    dry run reports the same "già presenti / vuoti" numbers as a real one —
    the Anteprima dialog shows them."""
    sync = fake.sync
    dry_sink, _ = _run(sync, "coll", force=True, dry_run=True)
    announced = dry_sink.of(RemoteIndexRead)[0]
    dry = dry_sink.of(EnvFinished)[0].result
    assert dry.empty == announced.n_empty
    assert dry.bytes == announced.bytes_to_download
    # n_daily is every daily entry the index listed, empty ones included
    # (the engine's len(index.daily), see tests/test_sync.py)
    assert announced.n_daily == dry.downloaded + dry.present + dry.empty

    wet_sink, _ = _run(sync, "coll", force=True, dry_run=False)
    wet = wet_sink.of(EnvFinished)[0].result
    assert (dry.status, dry.downloaded, dry.present, dry.empty, dry.bytes) == (
        wet.status, wet.downloaded, wet.present, wet.empty, wet.bytes
    )


# ------------------------------------------------------------ coverage_days ---

def test_coverage_days_fake_agrees_with_real_on_the_same_mirror(fake, mirror):
    """``FakeIndexApi.coverage_days`` must compute the same thing the real
    facade does from an actual mirror on disk — both call the same pure
    ``qtrequestory.core.daily.classify_days``, so this pins the wiring, not
    the algorithm (that is ``tests/test_daily.py``'s job).
    """
    cfg = dataclasses.replace(
        default_config(),
        mirror_root=mirror.root,
        environments=[Environment("coll", "https://example.invalid/coll/")],
    )
    real_index = IndexService(lambda: cfg)
    today = date(2026, 9, 22)

    real_result = real_index.coverage_days("coll", days=30, today=today)

    # Line the fake up with the exact same days the `mirror` fixture wrote to
    # disk for "coll" (see tests/conftest.py): 2026-09-18, 2026-09-15, 2026-08-03.
    mirror_days = {day for (env, day) in mirror.files if env == "coll"}
    fake.index.set_local_days("coll", mirror_days)
    fake_result = fake.index.coverage_days("coll", days=30, today=today)

    assert fake_result == real_result
    assert real_result.first_local == date(2026, 8, 3)
    assert real_result.present == frozenset(mirror_days)


def test_coverage_days_fake_agrees_with_real_on_every_kind_of_day(fake, mirror):
    """Empty local days and the sync state's listing memory: the fake's knobs
    must produce exactly what the facade reads from disk and state."""
    from qtrequestory.core.daily import local_path
    from qtrequestory.core.state import SyncState

    cfg = dataclasses.replace(
        default_config(),
        mirror_root=mirror.root,
        environments=[Environment("coll", "https://example.invalid/coll/")],
    )
    empty_days = {date(2026, 9, 19), date(2026, 9, 16)}
    for day in empty_days:
        local_path(mirror.root, "coll", day).write_bytes(b"")
    listed = {date(2026, 9, 21), date(2026, 9, 20)}
    seen = {date(2026, 9, 17), date(2026, 8, 20)}
    st = SyncState(cfg.state_path).load()
    st.record_listing("coll", datetime(2026, 8, 21, 9, 0), oldest_listed=date(2026, 8, 20),
                      listed_nonempty=seen)
    st.record_listing("coll", datetime(2026, 9, 22, 9, 0), oldest_listed=date(2026, 9, 15),
                      listed_nonempty=listed)
    today = date(2026, 9, 22)

    real_result = IndexService(lambda: cfg).coverage_days("coll", days=40, today=today)

    fake.index.set_local_days("coll", {day for (env, day) in mirror.files if env == "coll"}, empty=empty_days)
    fake.index.set_server_days("coll", listed=listed, seen=seen)
    fake_result = fake.index.coverage_days("coll", days=40, today=today)

    assert fake_result == real_result
    assert real_result.empty == frozenset(empty_days)
    assert real_result.pending == (date(2026, 9, 20), date(2026, 9, 21))
    assert real_result.lost == (date(2026, 8, 20), date(2026, 9, 17))
    assert real_result.unknown and all(d.weekday() < 5 for d in real_result.unknown)


# ---------------------------------------------------- fake vs. real fidelity ---
#
# Each case below was a real divergence found by running the same call against
# ``CoreServices.real()`` and the fake: a UI test written against the fake
# passed while the shipped application would have behaved differently. Every
# case builds its own minimal real and fake services (never the shared `fake`
# fixture, which several of these cases need to reconfigure) and asserts the
# same behaviour holds for both, either by comparing results or by checking
# both raise the same exception type.


def _real_services(tmp_path: Path, environments: list[Environment], **cfg_kw) -> CoreServices:
    paths = AppPaths(tmp_path / "apphome").ensure()
    cfg = dataclasses.replace(
        default_config(), mirror_root=tmp_path / "mirror", environments=environments, **cfg_kw
    )
    save_config(cfg, paths.config_file)
    return CoreServices.real(paths)


def _case_run_none_excludes_disabled_envs(tmp_path: Path) -> None:
    """``run(envs=None)`` -> ``config.enabled_environments()`` (``core.sync``),
    not "every configured name" — a disabled env must never be synced by a
    plain ``--sync``."""
    stub = StubServer()
    stub.start()
    try:
        stub.add("/svil/", autoindex_html([("20260918.txt", "18-Sep-2026 18:30", 4)]))
        stub.add("/svil/20260918.txt", b"x" * 4)
        real = _real_services(tmp_path / "real", [
            Environment("svil", stub.url + "/svil/", enabled=True),
            Environment("coll", stub.url + "/coll/", enabled=False),
        ])
        sink = CollectingSink()
        real.sync.run(None, force=True, dry_run=False, sink=sink, cancel=CancelToken())
        real_envs = [e.env for e in sink.of(EnvFinished)]
        assert not any("/coll/" in path for _, path in stub.requests)
    finally:
        stub.stop()

    fake = build_fake_core(tmp_path / "fake")
    fake.config.config = dataclasses.replace(
        fake.config.config,
        environments=[
            Environment("svil", "https://example.invalid/svil/", enabled=True),
            Environment("coll", "https://example.invalid/coll/", enabled=False),
        ],
    )
    fake_sink = CollectingSink()
    fake.sync.run(None, force=True, dry_run=False, sink=fake_sink, cancel=CancelToken())
    fake_envs = [e.env for e in fake_sink.of(EnvFinished)]

    assert real_envs == ["svil"]
    assert fake_envs == ["svil"]


def _case_unknown_env_in_run_raises(tmp_path: Path) -> None:
    """An explicit, unconfigured name is ``UnknownEnvironment`` before
    anything starts (``Config.require_env``, used by ``SyncEngine.run``) —
    not a quiet, empty, exit-0 run."""
    real = _real_services(tmp_path / "real", [Environment("coll", "https://example.invalid/coll/")])
    with pytest.raises(UnknownEnvironment):
        real.sync.run(["nope"], sink=CollectingSink(), cancel=CancelToken())

    fake = build_fake_core(tmp_path / "fake")
    with pytest.raises(UnknownEnvironment):
        fake.sync.run(["nope"], sink=CollectingSink(), cancel=CancelToken())


def _case_register_without_exe_raises(tmp_path: Path) -> None:
    """``register()`` with no executable to schedule is ``SchedulerError``
    ("running from source"), before ``schtasks`` is even invoked."""
    import subprocess

    def runner(args: list[str]) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

    real_sched = facade.SchedulerService(runner=runner, exe_provider=lambda: None)
    with pytest.raises(SchedulerError):
        real_sched.register()

    fake_sched = FakeSchedulerApi(exe=None)
    with pytest.raises(SchedulerError):
        fake_sched.register()


def _case_env_status_updates_after_run(tmp_path: Path) -> None:
    """A successful run must be visible in the NEXT ``env_status`` call —
    ``sync_page.refresh_cards`` re-reads it right after "Sincronizza ora"."""
    stub = StubServer()
    stub.start()
    try:
        stub.add("/coll/", autoindex_html([("20260918.txt", "18-Sep-2026 18:30", 4)]))
        stub.add("/coll/20260918.txt", b"x" * 4)
        real = _real_services(tmp_path / "real", [Environment("coll", stub.url + "/coll/")])
        before = real.sync.env_status("coll")
        real.sync.run(["coll"], force=True, dry_run=False, sink=CollectingSink(), cancel=CancelToken())
        after = real.sync.env_status("coll")
    finally:
        stub.stop()

    fake = build_fake_core(tmp_path / "fake")
    fake_before = fake.sync.env_status("svil")  # never-synced by default
    fake.sync.run(["svil"], force=True, dry_run=False, sink=CollectingSink(), cancel=CancelToken())
    fake_after = fake.sync.env_status("svil")

    assert before.last_success is None
    assert after.last_success is not None
    assert after.index_pending == 0

    assert fake_before.last_success is None
    assert fake_after.last_success is not None
    assert fake_after.index_pending == 0


def _case_config_load_returns_a_fresh_object(tmp_path: Path) -> None:
    """Two ``load()`` calls never return the SAME object — the real one
    re-parses ``config.json`` every time, so a caller mutating what it got
    back cannot corrupt what the next ``load()`` answers."""
    paths = AppPaths(tmp_path / "real" / "apphome").ensure()
    save_config(default_config(), paths.config_file)
    real_config = facade.ConfigService(paths)
    a, b = real_config.load(), real_config.load()
    assert a is not b
    a.mirror_root = Path("mutated-by-the-test")
    assert real_config.load().mirror_root != Path("mutated-by-the-test")

    fake = build_fake_core(tmp_path / "fake")
    fa, fb = fake.config.load(), fake.config.load()
    assert fa is not fb
    fa.mirror_root = Path("mutated-by-the-test")
    assert fake.config.load().mirror_root != Path("mutated-by-the-test")


def _case_list_template_keys_breaks_ties_by_count_then_name(tmp_path: Path) -> None:
    """``ORDER BY MAX(day) DESC, COUNT(*) DESC, template_key`` — same day, so
    the count and then the alphabetical tie-break decide, not encounter order."""
    # Deliberately NOT in "correct answer" order: KEY_A/KEY_C come first and
    # every KEY_B last, so a sort that (bug-for-bug) only orders by day and
    # falls back to encounter order would print [KEY_A, KEY_C, KEY_B] —
    # visibly different from the expected [KEY_B, KEY_A, KEY_C] — instead of
    # accidentally matching it, which is exactly how Important #13 (the
    # pick-best test) went unnoticed.
    real_root = tmp_path / "real_mirror"
    entries = [
        (entry_name(FDI_A, "KEY_A", "1a2b3c0200000004"), synthetic_body(FDI_A, "KEY_A")),
        (entry_name(FDI_A, "KEY_C", "1a2b3c0200000005"), synthetic_body(FDI_A, "KEY_C")),
        (entry_name(FDI_A, "KEY_B", "1a2b3c0200000001"), synthetic_body(FDI_A, "KEY_B")),
        (entry_name(FDI_A, "KEY_B", "1a2b3c0200000002"), synthetic_body(FDI_A, "KEY_B")),
        (entry_name(FDI_A, "KEY_B", "1a2b3c0200000003"), synthetic_body(FDI_A, "KEY_B")),
    ]
    make_daily_file(real_root, "coll", date(2026, 9, 18), entries)
    cfg = dataclasses.replace(
        default_config(), mirror_root=real_root, environments=[Environment("coll", "https://example.invalid/coll/")]
    )
    real_index = IndexService(lambda: cfg)
    real_index.update(["coll"], full_rebuild=True, sink=CollectingSink(), cancel=CancelToken())
    real_order = real_index.list_template_keys("coll")
    assert real_order == ["KEY_B", "KEY_A", "KEY_C"]

    fake = build_fake_core(tmp_path / "fake")
    extra_specs = [
        (date(2026, 9, 18), FDI_A, "KEY_A", "1a2b3c0200000004", 2, None),
        (date(2026, 9, 18), FDI_A, "KEY_C", "1a2b3c0200000005", 2, None),
        (date(2026, 9, 18), FDI_A, "KEY_B", "1a2b3c0200000001", 2, None),
        (date(2026, 9, 18), FDI_A, "KEY_B", "1a2b3c0200000002", 2, None),
        (date(2026, 9, 18), FDI_A, "KEY_B", "1a2b3c0200000003", 2, None),
    ]
    fake.index.hits = [_hit(100 + i, spec, tmp_path / "fake" / "mirror") for i, spec in enumerate(extra_specs)]
    fake_order = fake.index.list_template_keys("coll")

    assert fake_order == real_order


def _case_plan_is_scoped_to_requested_envs(tmp_path: Path) -> None:
    """``plan(["svil"])`` must not also report "coll"'s backlog."""
    real_root = tmp_path / "real_mirror"
    make_daily_file(real_root, "coll", date(2026, 9, 18), [(entry_name(FDI_A, KEY_CTE), synthetic_body(FDI_A, KEY_CTE))])
    make_daily_file(real_root, "svil", date(2026, 9, 16), [(entry_name(FDI_A, KEY_SINT), synthetic_body(FDI_A, KEY_SINT))])
    cfg = dataclasses.replace(
        default_config(), mirror_root=real_root,
        environments=[Environment("coll", "https://example.invalid/coll/"),
                      Environment("svil", "https://example.invalid/svil/")],
    )
    real_index = IndexService(lambda: cfg)
    real_plan = real_index.plan(["svil"])
    assert real_plan.to_scan and {f.env for f in real_plan.to_scan} == {"svil"}

    fake = build_fake_core(tmp_path / "fake")
    fake.index.pending = [
        LocalDailyFile("coll", date(2026, 9, 18), Path("coll.txt"), 10, 0),
        LocalDailyFile("svil", date(2026, 9, 16), Path("svil.txt"), 10, 1),
    ]
    fake_plan = fake.index.plan(["svil"])
    assert fake_plan.to_scan and {f.env for f in fake_plan.to_scan} == {"svil"}


def _case_write_temp_file_honours_retention(tmp_path: Path) -> None:
    """``retention_hours`` from the CURRENT configuration prunes the output
    dir before writing — an old leftover extraction must not survive a
    ``--find``/preview once ``output_retention_hours`` says it should be gone."""
    hit = _hit(1, (date(2026, 9, 18), FDI_A, KEY_CTE, "1a2b3c0200000001", 2, None), tmp_path)
    old = time_mod.time() - 2 * 3600  # 2h old; retention below is 1h

    real_out = tmp_path / "real_out"
    real_out.mkdir()
    real_stale = real_out / "old.json"
    real_stale.write_text("x", encoding="utf-8")
    os.utime(real_stale, (old, old))
    real_cfg = dataclasses.replace(default_config(), output_dir=real_out, output_retention_hours=1)
    facade.ExtractService(lambda: real_cfg).write_temp_file(hit, "{}")
    assert not real_stale.exists()

    fake_out = tmp_path / "fake_out"
    fake_out.mkdir()
    fake_stale = fake_out / "old.json"
    fake_stale.write_text("x", encoding="utf-8")
    os.utime(fake_stale, (old, old))
    fake_cfg = dataclasses.replace(default_config(), output_retention_hours=1)
    FakeExtractApi(fake_out, lambda: fake_cfg).write_temp_file(hit, "{}")
    assert not fake_stale.exists()


# ------------------------------------------------------------ officina ---
#
# The fake Officina is the real service with an in-process generator; these
# cases run the same script against the real service talking HTTP to a local
# server (tests/officina/test_generator.FakeServer) and compare everything the
# UI can see: names, ids, version numbers and types, files on disk, what was
# sent, and every refusal/failure reason.

_OFFICINA_PAYLOAD = {
    "documents": [{"template": {"templateKey": "MOD_TEST_A"},
                   "attributes": [{"key": "attachmentId", "value": "att-0"},
                                  {"key": "attachmentUrl", "value": "https://example.invalid/c/MOD_TEST_A.pdf"}]}],
    "customers": [{"name": "Cliente di prova"}],
}


def _officina_pair(tmp_path: Path):
    """(real service + its server, fake bundle), both with svil enabled and
    coll configured but disabled, and a payload file."""
    from qtrequestory.core.config import GeneratorEndpoint
    from qtrequestory.officina.service import OfficinaService
    from tests.officina.test_generator import FakeServer

    server = FakeServer()
    server.canned.body = canned_pdf()
    fake = build_fake_core(tmp_path / "fake")
    fake.config.config.officina.generators.append(
        GeneratorEndpoint("coll", "https://example.invalid/coll/documentGenerator", enabled=False))
    real_cfg = dataclasses.replace(
        default_config(), mirror_root=tmp_path / "real" / "mirror",
        officina=dataclasses.replace(fake.config.config.officina, root=tmp_path / "real" / "officina",
                                     generators=[GeneratorEndpoint("svil", server.url),
                                                 GeneratorEndpoint("coll", server.url, enabled=False)]),
    )
    real = OfficinaService(lambda: real_cfg)
    src = tmp_path / "payload.json"
    src.write_text(__import__("json").dumps(_OFFICINA_PAYLOAD), encoding="utf-8")
    return real, server, fake.officina, fake, src


#: Added by http.client on the wire, not by the service: the fake never sees them.
_TRANSPORT_HEADERS = frozenset({"host", "user-agent", "accept-encoding", "connection", "content-length"})
#: Different on every call (a new uuid4, the clock): only their presence is compared.
_PER_CALL_HEADERS = frozenset({"correlation_id", "current_timestamp"})


def _app_headers(headers: dict[str, str]) -> dict[str, str]:
    """The headers the service sent, lower-cased; per-call values blanked."""
    low = {k.lower(): v for k, v in headers.items() if k.lower() not in _TRANSPORT_HEADERS}
    return {k: ("<per call>" if k in _PER_CALL_HEADERS else v) for k, v in low.items()}


def _layout(folder: Path) -> list[str]:
    return sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file())


def _case_officina_create_case_and_generate(tmp_path: Path) -> None:
    import json

    real, server, fake, bundle, src = _officina_pair(tmp_path)
    try:
        seen = {}
        for name, api in (("real", real), ("fake", fake)):
            before = api.initiatives()
            ini = api.create_initiative("Iniziativa di prova")
            case = api.case_from_file(ini, src, "MOD_TEST_A", "Variante Uno")
            runs = [api.generate(ini, case, "asis"), api.generate(ini, case, "tobe"), api.generate(ini, case, "tobe")]
            root = api.workspace_root()
            seen[name] = {
                "before": before,
                "names": [i.name for i in api.initiatives()],
                "case": (case.id, case.key, case.variant, case.env, case.source_fdi),
                "versions": [(v.kind, v.number, v.doc_type, v.path.relative_to(root).as_posix(), sorted(v.meta))
                             for v, _ in runs],
                "results": [(r.ok, r.status, r.doc_type, r.reason) for _, r in runs],
                "files": _layout(root),
                "reloaded": [(c.id, [v.number for v in c.tobe_versions()], c.asis().number)
                             for c in api.load("Iniziativa di prova").cases],
            }
        real_sent = [json.loads(body) for _, body in server.requests]
        fake_sent = [r.payload for r in fake.requests]
        real_headers = [_app_headers(h) for h, _ in server.requests]
        fake_headers = [_app_headers(r.headers) for r in fake.requests]
    finally:
        server.close()
    assert seen["real"] == seen["fake"]
    assert seen["real"]["before"] == []
    assert [v[1] for v in seen["real"]["versions"]] == [0, 1, 2]
    assert real_sent == fake_sent and len(real_sent) == 3
    assert real_headers == fake_headers and len(real_headers) == 3
    assert real_headers[0]["template_key"] == "MOD_TEST_A" and real_headers[0]["postman-token"]
    assert {"correlation_id", "current_timestamp"} <= set(real_headers[0])
    assert "attachmentUrl" not in json.dumps(real_sent)


def _case_officina_refusals_and_failures(tmp_path: Path) -> None:
    real, server, fake, bundle, src = _officina_pair(tmp_path)
    target = tmp_path / "atteso.pdf"
    target.write_bytes(canned_pdf("atteso"))
    html = b"<!DOCTYPE html><html><body>" + b"<p>MOD_TEST pagina</p>" * 40 + b"</body></html>"
    try:
        outcome = {}
        for name, api in (("real", real), ("fake", fake)):
            ini = api.create_initiative("I")
            case = api.case_from_file(ini, src, "MOD_TEST_A")
            got = []
            case.env = "coll"                                   # disabled generator
            got.append(api.generate(ini, case, "tobe"))
            case.env = "ignoto"                                 # unknown generator
            got.append(api.generate(ini, case, "tobe"))
            case.env = "svil"
            api.set_target(case, target)
            if name == "real":
                server.canned.status, server.canned.body = 500, b"errore"
            else:
                fake.set_response(b"errore", status=500)
            got.append(api.generate(ini, case, "tobe"))         # HTTP 500
            if name == "real":
                server.canned.status, server.canned.body = 200, html
            else:
                fake.set_response(html)
            got.append(api.generate(ini, case, "tobe"))         # HTML for a PDF case
            outcome[name] = ([(v, r.ok, r.status, r.reason) for v, r in got],
                             _layout(case.folder))
    finally:
        server.close()
    assert outcome["real"] == outcome["fake"]
    reasons = [r for _, _, _, r in outcome["real"][0]]
    assert "non è attivo" in reasons[0] and "non è configurato" in reasons[1]
    assert "HTTP 500" in reasons[2] and "risposta HTML per un caso PDF" in reasons[3]
    assert not any(f.startswith("tobe/") for f in outcome["real"][1])


def _case_officina_delivery(tmp_path: Path) -> None:
    """Plan, conflicts, delivery (with the zip) and the remembered destination."""
    real, server, fake, bundle, src = _officina_pair(tmp_path)
    target = tmp_path / "atteso.pdf"
    target.write_bytes(canned_pdf("atteso"))
    try:
        seen = {}
        for name, api in (("real", real), ("fake", fake)):
            ini = api.create_initiative("Consegna")
            first = api.case_from_file(ini, src, "MOD_TEST_A", "uno")
            second = api.case_from_file(ini, src, "MOD_TEST_A", "due")
            for case in (first, second):
                api.set_target(case, target)
                api.generate(ini, case, "tobe")
            ini = api.load("Consegna")
            dest = tmp_path / f"consegne-{name}"
            before = api.last_delivery_destination(ini)
            plan = api.delivery_plan(ini, [c.id for c in ini.cases])
            report = api.deliver(ini, plan.items, dest, on_conflict=lambda _p: "skip", make_zip=True)
            again = api.delivery_conflicts(ini, plan.items, dest, make_zip=True)
            seen[name] = {
                "before": before,
                "items": [(i.case_id, i.dest_rel) for i in plan.items],
                "missing": [(m.case_id, m.slot, m.reason) for m in plan.missing],
                "delivered": [p.relative_to(dest).as_posix() for p in report.delivered],
                "failed": report.failed,
                "conflicts": [p.relative_to(dest).as_posix() for p in again],
                "last": api.last_delivery_destination(api.load("Consegna")) == dest,
            }
    finally:
        server.close()
    assert seen["real"] == seen["fake"]
    assert seen["real"]["before"] is None and seen["real"]["last"] is True
    assert seen["real"]["delivered"][-1] == "Consegna.zip"
    assert len(seen["real"]["conflicts"]) == len(seen["real"]["delivered"])


def _case_empty_today_reads_the_same(tmp_path: Path) -> None:
    """1.1.1: a quiet today after the compaction — not fresh (the next run
    re-lists), read as "empty_today" by ``freshness`` and ``env_status``."""
    from qtrequestory.core.state import SyncState

    cfg = dataclasses.replace(default_config(), mirror_root=tmp_path / "real" / "mirror",
                              environments=[Environment("svil", "https://example.invalid/svil/")])
    st = SyncState(cfg.state_path).load()
    when = datetime(2026, 9, 24, 22, 33)
    st.record_listing("svil", when, oldest_listed=date(2026, 9, 21),
                      listed_nonempty=(date(2026, 9, 23),),
                      listed_empty=(date(2026, 9, 22), date(2026, 9, 24)))
    st.mark_success("svil", when, newest_day=date(2026, 9, 23))
    real = facade.SyncService(lambda: cfg, clock=lambda: datetime(2026, 9, 24, 22, 40))

    fake = build_fake_core(tmp_path / "fake").sync
    fake.set_empty_today("svil")

    def seen(sync) -> tuple:
        status = sync.env_status("svil")
        return sync.is_fresh("svil"), sync.freshness("svil"), status.fresh, status.freshness

    assert seen(real) == seen(fake) == (False, "empty_today", False, "empty_today")


_FIDELITY_CASES = [
    ("run_none_excludes_disabled_envs", _case_run_none_excludes_disabled_envs),
    ("unknown_env_in_run_raises", _case_unknown_env_in_run_raises),
    ("register_without_exe_raises", _case_register_without_exe_raises),
    ("env_status_updates_after_run", _case_env_status_updates_after_run),
    ("config_load_returns_a_fresh_object", _case_config_load_returns_a_fresh_object),
    ("list_template_keys_breaks_ties_by_count_then_name", _case_list_template_keys_breaks_ties_by_count_then_name),
    ("plan_is_scoped_to_requested_envs", _case_plan_is_scoped_to_requested_envs),
    ("write_temp_file_honours_retention", _case_write_temp_file_honours_retention),
    ("officina_create_case_and_generate", _case_officina_create_case_and_generate),
    ("officina_refusals_and_failures", _case_officina_refusals_and_failures),
    ("officina_delivery", _case_officina_delivery),
    ("empty_today_reads_the_same", _case_empty_today_reads_the_same),
]


@pytest.mark.parametrize("case", [fn for _, fn in _FIDELITY_CASES], ids=[name for name, _ in _FIDELITY_CASES])
def test_fake_matches_real(case, tmp_path: Path):
    """``check_reachable`` is a documented, intentional exception — see its
    docstring in ``tests/fakes/fake_core.py``: it is keyed on the env NAME by
    design (every UI knob that sets outcomes works that way), so it never
    probes ``env.url`` and is not pinned here."""
    case(tmp_path)


def test_mirror_root_errors_fake_matches_real(tmp_path: Path) -> None:
    """Final review #1: the GUI gates on ``config.mirror_root_errors`` exactly
    like the CLI; the fake must answer what the real service answers."""
    paths = AppPaths(tmp_path / "real" / "apphome").ensure()
    real = facade.ConfigService(paths)
    fake = build_fake_core(tmp_path / "fake").config
    base = default_config()
    for root in (Path(""), Path("relative/logs"), tmp_path / "mirror"):
        cfg = dataclasses.replace(base, mirror_root=root)
        assert fake.mirror_root_errors(cfg) == real.mirror_root_errors(cfg)
    assert real.mirror_root_errors(dataclasses.replace(base, mirror_root=Path(""))) != []
    assert real.mirror_root_errors(dataclasses.replace(base, mirror_root=tmp_path)) == []


def test_fake_officina_knobs(fake, tmp_path: Path):
    """The fake Officina's knobs: network error, scripted compare, compare
    error, and a canned HTML->PDF print under the case cache."""
    from qtrequestory.officina.compare.textdiff import TextComparison
    from qtrequestory.officina.service import CompareError

    api = fake.officina
    assert fake.officina is api
    assert api.workspace_root() == tmp_path / "core" / "officina"
    src = tmp_path / "p.json"
    src.write_text('{"documents": []}', encoding="utf-8")
    ini = api.create_initiative("I")
    case = api.case_from_file(ini, src, "MOD_TEST_A")

    api.set_network_error("rete assente")
    version, result = api.generate(ini, case, "asis")
    assert version is None and result.reason == "errore di rete: rete assente"
    assert [r.headers.get("Template_key") for r in api.requests] == ["MOD_TEST_A"]

    api.set_response()
    asis, result = api.generate(ini, case, "asis")
    assert result.ok and asis.doc_type == "pdf"
    target = tmp_path / "atteso.pdf"
    target.write_bytes(canned_pdf("MOD_TEST documento generato dal generatore finto"))
    tgt = api.set_target(case, target)
    assert api.compare(tgt, asis).equal

    scripted = TextComparison([], True, True, False, "nota scritta dal test")
    api.set_comparison(scripted)
    assert api.compare(tgt, asis) is scripted
    api.set_compare_error("Edge non trovato")
    with pytest.raises(CompareError, match="Edge non trovato"):
        api.compare(tgt, asis)
    assert len(api.compare_calls) == 3

    api.set_compare_error(None)
    api.set_comparison(None)
    html = tmp_path / "email.html"
    html.write_bytes(b"<!DOCTYPE html><html><body><p>MOD_TEST documento generato dal generatore finto</p></body></html>")
    html_target = api.set_target(case, html)
    assert api.compare(html_target, asis).equal
    assert api.conversions[0][1].parent == case.folder / "cache"


def test_fake_officina_scripts_one_case_of_a_batch(fake, tmp_path: Path):
    """Task 7's batch: only the second case fails, the others succeed."""
    import threading

    api = fake.officina
    src = tmp_path / "p.json"
    src.write_text('{"documents": []}', encoding="utf-8")
    ini = api.create_initiative("Batch")
    cases = [api.case_from_file(ini, src, key) for key in ("MOD_TEST_A", "MOD_TEST_B", "MOD_TEST_C")]
    api.set_response_for("MOD_TEST_B", b"errore del generatore", status=500)

    results = {}

    def run(case) -> None:
        results[case.key] = api.generate(ini, case, "asis")

    threads = [threading.Thread(target=run, args=(c,)) for c in cases]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert {k: r.ok for k, (_, r) in results.items()} == {"MOD_TEST_A": True, "MOD_TEST_B": False, "MOD_TEST_C": True}
    assert results["MOD_TEST_B"][1].status == 500

    api.set_response_for("MOD_TEST_B", None)  # back to the default answer
    assert api.generate(ini, cases[1], "asis")[1].ok


def test_fake_officina_responder_decides_per_request(fake, tmp_path: Path):
    import urllib.error

    api = fake.officina
    src = tmp_path / "p.json"
    src.write_text('{"documents": []}', encoding="utf-8")
    ini = api.create_initiative("R")
    case = api.case_from_file(ini, src, "MOD_TEST_A")

    def responder(request):
        if request.template_key == "MOD_TEST_A":
            raise urllib.error.URLError("rete assente")
        return 200, canned_pdf()

    api.set_responder(responder)
    version, result = api.generate(ini, case, "asis")
    assert version is None and result.reason == "errore di rete: rete assente"
    api.set_responder(None)
    assert api.generate(ini, case, "asis")[1].ok
