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

from pathlib import Path

import pytest

from qtrequestory.core.events import (
    CancelToken,
    CollectingSink,
    EnvFinished,
    EnvSkipped,
    FileFailed,
    FileStarted,
    IndexStarted,
    RemoteIndexRead,
)
from qtrequestory.ui.contracts import CoreServices
from tests.fakes.fake_core import ENVS, build_fake_core

#: An environment the fake does not know about: the wizard lets the user import
#: an environments.json with any names at all, so the knobs must cope.
UNKNOWN_ENV = "prod"


@pytest.fixture
def fake(tmp_path: Path) -> CoreServices:
    return build_fake_core(tmp_path / "core")


def _run(sync, env: str, **kw):
    sink = CollectingSink()
    report = sync.run([env], sink=sink, cancel=CancelToken(), **kw)
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


# ------------------------------------------------------- unknown env knobs ---

def test_knobs_tolerate_an_env_the_fake_does_not_know(fake):
    """``env_status`` answers for any name, so the setters must too: a UI test
    built on an imported environments.json must not die in a KeyError."""
    sync = fake.sync
    sync.set_unreachable(UNKNOWN_ENV)
    assert sync.check_reachable(UNKNOWN_ENV) is False
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

    sink, report = _run(sync, UNKNOWN_ENV, force=True, dry_run=False)
    assert sink.of(EnvFinished)[0].result.status == "ok"
    assert report.exit_code == 0


# --------------------------------------------------- cancelling a bad run ---

def test_cancelling_a_failing_run_is_cancelled_not_errors(fake):
    """The engine checks the token before every file, so a user who hits
    "Annulla" while files are failing gets exit 3 (annullato), not exit 1."""
    sync = fake.sync
    sync.set_failing("coll", 3)
    cancel = CancelToken()
    sink = CollectingSink()

    def cancelling(ev):
        sink(ev)
        if isinstance(ev, FileFailed):
            cancel.cancel()

    report = sync.run(["coll"], force=True, dry_run=False, sink=cancelling, cancel=cancel)
    assert sink.of(EnvFinished)[0].result.status == "cancelled"
    assert report.exit_code == 3
    assert len(sink.of(FileStarted)) == 1  # it stops at the cancel, not after all 3
    assert sink.of(IndexStarted) == []  # a cancelled sync never indexes


def test_cancelling_mid_file_stops_before_the_failure_is_reported(fake):
    """Cancelling while a file is in flight ends the env there: like the real
    engine, the interrupted transfer is not also reported as a failure."""
    sync = fake.sync
    sync.set_failing("coll", 3)
    cancel = CancelToken()
    sink = CollectingSink()

    def cancelling(ev):
        sink(ev)
        if isinstance(ev, FileStarted):
            cancel.cancel()

    report = sync.run(["coll"], force=True, dry_run=False, sink=cancelling, cancel=cancel)
    assert sink.of(FileFailed) == []
    assert sink.of(EnvFinished)[0].result.status == "cancelled"
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
