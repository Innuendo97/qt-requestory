"""Genera of exact calls (Ricerca's "Genera documento"): the request, its
problems, the order of the generators, the run on the Genera page and its retry.

The page runs on the fake core: the REAL ``OfficinaService`` with an
in-process generator (every request recorded) over the fake index (12
synthetic calls in the logs of ``coll``). Synthetic data only.
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import NO_PACKAGE, BatchReport, GeneratorEndpoint, Outcome, Target
from qtrequestory.ui.pages import officina_dialogs
from qtrequestory.ui.pages.genera_calls import calls_problems, calls_request, generator_order
from qtrequestory.ui.pages.genera_page import GeneraPage
from qtrequestory.ui.pages.genera_presenter import GeneraPresenter
from qtrequestory.ui.pages.genera_retry import retry_count, retry_targets
from tests.conftest import FDI_A, FDI_B, FDI_C, KEY_EMAIL, KEY_SINT

WAIT_MS = 8000
HTML = b"<!DOCTYPE html>\n<html><body>" + b"<p>MOD_TEST e-mail</p>" * 40 + b"</body></html>"


class FakeWindow:
    def __init__(self) -> None:
        self.toasts: list[tuple[str, str]] = []

    def show_toast(self, text: str, tone: str = "neutral", *_a, **_k) -> None:
        self.toasts.append((text, tone))

    def show_page(self, _key: str) -> None:
        pass

    def page(self, _key: str):
        return None


def _hit(fake_core, fdi: str, key: str):
    return next(h for h in fake_core.index.hits if h.fdi == fdi and h.template_key == key)


def _outcome(key: str, status: str, folders=(NO_PACKAGE,), fdi=None, exact_hit=None) -> Outcome:
    return Outcome(key=key, folders=tuple(folders), fdi=fdi, status=status, doc_type=None, files=(),
                   duration_ms=0, http_status=None, reason="", exact_hit=exact_hit)


def _two_generators(fake_core) -> None:
    cfg = fake_core.config.config
    coll = GeneratorEndpoint("coll", "https://example.invalid/coll/rest/api/submit-job/documentGenerator")
    fake_core.config.config = dataclasses.replace(cfg, officina=dataclasses.replace(
        cfg.officina, generators=[*cfg.officina.generators, coll]))


@pytest.fixture
def presenter(qapp, fake_core, tmp_path: Path) -> GeneraPresenter:
    p = GeneraPresenter(fake_core)
    p.activate()
    p.set_destination(tmp_path / "dest")
    return p


# -- the request ------------------------------------------------------------------------------

def test_the_request_sends_those_calls_with_html_always_saved_and_no_zip(presenter, fake_core, tmp_path):
    presenter.set_save_html(False)
    presenter.set_make_zip(True)
    presenter.set_header_rows([*presenter.header_rows, ("IMEL", "active")])  # an edit of this session
    older = _hit(fake_core, FDI_C, KEY_SINT)
    request = calls_request(presenter, [older, older], "svil")
    assert request.targets == (Target("call", KEY_SINT, (FDI_C,), hit=older),)
    assert (request.generator, request.source_env) == ("svil", "coll")
    assert request.save_html is True and request.make_zip is False
    assert request.header_rows[-1] == ("IMEL", "active")
    assert request.destination == tmp_path / "dest"


def test_problems_name_what_stops_the_calls(presenter):
    assert calls_problems(presenter, "svil") == []
    assert calls_problems(presenter, "coll") == [strings.GENERA_CALLS_GENERATOR_OFF.format(name="coll")]
    presenter.set_destination(Path("relativa"))
    assert calls_problems(presenter, "svil") == [strings.GENERA_CALLS_NEED_DESTINATION]
    presenter.set_destination(None)
    assert calls_problems(presenter, "svil") == [strings.GENERA_CALLS_NEED_DESTINATION]


def test_a_bad_header_row_is_a_problem(presenter):
    presenter.set_header_rows([*presenter.header_rows, ("IMEL", "riga\nspezzata")])
    (problem,) = calls_problems(presenter, "svil")
    assert problem.startswith(strings.GENERA_CALLS_HEADER_PROBLEM.split("{")[0]) and "IMEL" in problem


@pytest.mark.parametrize("generators, env, remembered, expected", [
    (["svil", "coll"], "coll", "svil", ["coll", "svil"]),   # the call's own environment first
    (["svil", "coll"], "test", "coll", ["coll", "svil"]),   # else the Genera tab's generator
    (["svil", "coll"], "test", "", ["svil", "coll"]),       # else the configured order
    (["svil"], "coll", "svil", ["svil"]),
    ([], "coll", "svil", []),
])
def test_generator_order(generators, env, remembered, expected):
    assert generator_order(generators, env, remembered) == expected


# -- the retry ---------------------------------------------------------------------------------

def test_a_retry_of_exact_calls_resends_those_calls(fake_core, tmp_path):
    a, b = _hit(fake_core, FDI_C, KEY_SINT), _hit(fake_core, FDI_A, KEY_SINT)
    report = BatchReport(tmp_path / "svil_x", (
        _outcome(KEY_SINT, "failed", (FDI_C,), FDI_C, exact_hit=a),
        _outcome(KEY_SINT, "ok", (FDI_A,), FDI_A, exact_hit=b),
        _outcome(KEY_SINT, "cancelled", (FDI_A,), FDI_A, exact_hit=b),
        _outcome(KEY_SINT, "cancelled", (FDI_A,), FDI_A, exact_hit=b),  # the same call: once
    ), (), True)
    assert retry_targets(report) == (Target("call", KEY_SINT, (FDI_C,), hit=a),
                                     Target("call", KEY_SINT, (FDI_A,), hit=b))
    assert retry_count(report) == 2


def test_the_retry_of_exact_calls_goes_to_the_generator_of_now(presenter, fake_core, tmp_path):
    """Like every retry: the generator the Genera tab shows NOW, not the one
    the calls went to; the same exact calls, HTML still always saved, no zip."""
    _two_generators(fake_core)
    presenter.reload_config()
    presenter.set_save_html(False)
    presenter.set_make_zip(True)
    hit = _hit(fake_core, FDI_C, KEY_SINT)
    previous = calls_request(presenter, [hit], "coll")
    report = BatchReport(tmp_path / "coll_x", (
        _outcome(KEY_SINT, "failed", (FDI_C,), FDI_C, exact_hit=hit),), (), False)
    assert presenter.generator == "svil"
    request = presenter.retry_request(report, previous)
    assert request.targets == (Target("call", KEY_SINT, (FDI_C,), hit=hit),)
    assert (request.generator, request.save_html, request.make_zip) == ("svil", True, False)
    assert request.source_env == previous.source_env  # where those calls were logged
    presenter.set_generator("coll")
    assert presenter.retry_request(report, previous).generator == "coll"
    # a run of the tab itself: the tab's choices of now, options included
    keys_report = BatchReport(tmp_path / "svil_x", (_outcome("MOD_TEST_A", "failed"),), (), False)
    keys_retry = presenter.retry_request(keys_report, previous)
    assert (keys_retry.generator, keys_retry.save_html, keys_retry.make_zip) == ("coll", False, True)


# -- on the page -------------------------------------------------------------------------------

@pytest.fixture
def page(qtbot, fake_core, runner, tmp_path: Path) -> GeneraPage:
    dest = tmp_path / "dest"
    dest.mkdir()
    page = GeneraPage(fake_core, runner, FakeWindow())
    qtbot.addWidget(page)
    page.presenter.set_destination(dest)
    return page


class Notified:
    def __init__(self) -> None:
        self.calls: list[tuple[BatchReport | None, str]] = []

    def __call__(self, report, problem) -> None:
        self.calls.append((report, problem))


def _wait(qtbot, notified: Notified) -> BatchReport:
    qtbot.waitUntil(lambda: bool(notified.calls), timeout=WAIT_MS)
    (report, problem), = notified.calls
    assert problem == "" and report is not None
    return report


def test_generating_calls_sends_exactly_those_payloads(qtbot, page, fake_core):
    older = _hit(fake_core, FDI_C, KEY_SINT)  # not the newest call of the key
    other = _hit(fake_core, FDI_B, KEY_SINT)
    notified = Notified()
    assert page.generate_calls([older, other], "svil", notify=notified) == (True, "")
    report = _wait(qtbot, notified)
    sent = [r.payload for r in fake_core.officina.requests]
    assert sent == [json.loads(fake_core.index.bodies[h.entry_id]) for h in (older, other)]
    assert [o.files[0].relative_to(report.run_dir).parts for o in report.outcomes] == [
        (FDI_C, f"{KEY_SINT}.pdf"), (FDI_B, f"{KEY_SINT}.pdf")]
    qtbot.waitUntil(lambda: not page.is_running(), timeout=WAIT_MS)
    assert page.report is report and len(page.results.row_texts()) == 2  # the tab shows the run


def test_the_page_says_nothing_itself_when_the_caller_is_told(qtbot, page, fake_core):
    notified = Notified()
    page.generate_calls([_hit(fake_core, FDI_C, KEY_SINT)], "svil", notify=notified)
    _wait(qtbot, notified)
    qtbot.waitUntil(lambda: not page.is_running(), timeout=WAIT_MS)
    assert page._window.toasts == []  # the caller's toast, not the tab's


def test_html_is_saved_and_remembered_even_with_the_option_off(qtbot, page, fake_core):
    page.presenter.set_save_html(False)
    fake_core.officina.set_response(HTML)
    notified = Notified()
    page.generate_calls([_hit(fake_core, FDI_C, KEY_EMAIL)], "svil", notify=notified)
    (outcome,) = _wait(qtbot, notified).outcomes
    assert outcome.status == "ok" and outcome.files[0].suffix == ".html"
    memory = json.loads(fake_core.paths.genera_html_file.read_text(encoding="utf-8"))
    assert memory["html_keys"] == [KEY_EMAIL]


def test_no_destination_sends_nothing_and_says_why(qtbot, page, fake_core):
    page.presenter.set_destination(None)
    notified = Notified()
    assert page.generate_calls([_hit(fake_core, FDI_C, KEY_SINT)], "svil", notify=notified) == (
        False, strings.GENERA_CALLS_NEED_DESTINATION)
    assert fake_core.officina.requests == [] and not page.is_running() and notified.calls == []


def test_a_generator_not_enabled_sends_nothing(qtbot, page, fake_core):
    started, reason = page.generate_calls([_hit(fake_core, FDI_C, KEY_SINT)], "prod")
    assert not started and reason == strings.GENERA_CALLS_GENERATOR_OFF.format(name="prod")
    assert fake_core.officina.requests == []


def test_one_run_at_a_time(qtbot, page, fake_core):
    hit = _hit(fake_core, FDI_C, KEY_SINT)
    notified = Notified()
    assert page.generate_calls([hit], "svil", notify=notified)[0]
    assert page.generate_calls([hit], "svil") == (False, strings.GENERA_ALREADY_RUNNING)
    _wait(qtbot, notified)


def test_over_twenty_calls_are_confirmed_first(qtbot, page, fake_core, monkeypatch):
    asked: list[tuple[object, str, str]] = []
    monkeypatch.setattr(officina_dialogs, "confirm", lambda parent, t, x, **_kw: asked.append((parent, t, x)) or False)
    base = _hit(fake_core, FDI_C, KEY_SINT)
    hits = [dataclasses.replace(base, seq=base.seq + n) for n in range(21)]
    parent = object()
    assert page.generate_calls(hits, "svil", parent=parent) == (False, "")
    ((asked_parent, title, text),) = asked
    assert asked_parent is parent and "21" in title and "svil" in text
    assert fake_core.officina.requests == [] and not page.is_running()


def test_running_changed_follows_the_run(qtbot, page, fake_core):
    seen: list[bool] = []
    page.running_changed.connect(seen.append)
    notified = Notified()
    page.generate_calls([_hit(fake_core, FDI_C, KEY_SINT)], "svil", notify=notified)
    _wait(qtbot, notified)
    qtbot.waitUntil(lambda: seen[-1:] == [False], timeout=WAIT_MS)
    assert seen == [True, False]


def test_a_refusal_of_the_core_reaches_the_caller(qtbot, page, fake_core, monkeypatch):
    def refuse(_request, **_kw):
        raise ValueError("la cartella di destinazione deve essere un percorso assoluto")

    monkeypatch.setattr(fake_core.officina, "batch_run", refuse)
    notified = Notified()
    page.generate_calls([_hit(fake_core, FDI_C, KEY_SINT)], "svil", notify=notified)
    qtbot.waitUntil(lambda: bool(notified.calls), timeout=WAIT_MS)
    assert notified.calls == [(None, "la cartella di destinazione deve essere un percorso assoluto")]


def test_the_tab_retry_resends_the_same_calls_to_the_generator_shown(qtbot, page, fake_core):
    _two_generators(fake_core)
    page.on_config_changed(fake_core.config.config)
    older = _hit(fake_core, FDI_C, KEY_SINT)
    fake_core.officina.set_response(b"guasto", 500)
    notified = Notified()
    page.generate_calls([older], "coll", notify=notified)
    first = _wait(qtbot, notified)
    qtbot.waitUntil(lambda: not page.is_running(), timeout=WAIT_MS)
    assert [o.status for o in first.outcomes] == ["failed"] and not page.results.retry_button.isHidden()
    assert "/coll/" in fake_core.officina.requests[0].url
    assert page.generator_combo.currentText() == "svil"  # what the tab shows, "con le scelte di ora"
    fake_core.officina.set_response(None)
    before = len(fake_core.officina.requests)
    qtbot.mouseClick(page.results.retry_button, Qt.MouseButton.LeftButton)
    qtbot.waitUntil(lambda: page.report is not None and page.report is not first
                    and not page.is_running(), timeout=WAIT_MS)
    (again,) = fake_core.officina.requests[before:]
    assert again.payload == json.loads(fake_core.index.bodies[older.entry_id])
    assert "/svil/" in again.url and page.report.run_dir.name.startswith("svil_")
    assert [o.status for o in page.report.outcomes] == ["ok"]
    assert page._window.toasts  # a retry started from the tab is the tab's: its own toast


def test_an_unshown_tab_still_sends_its_headers(qtbot, page, fake_core):
    assert not page.presenter.activated
    notified = Notified()
    page.generate_calls([_hit(fake_core, FDI_C, KEY_SINT)], "svil", notify=notified)
    _wait(qtbot, notified)
    (request,) = fake_core.officina.requests
    assert request.template_key == KEY_SINT and page.presenter.activated
