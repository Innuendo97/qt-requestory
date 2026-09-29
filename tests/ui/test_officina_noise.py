"""Officina phase 2 (U6): the "Regole di rumore…" dialog (spec §4.2 step 5, §7.5).

The dialog alone with a scripted counter (debounce, spinner, errors on their
row, names unique across levels), then from the page on the fake core: the
board saves with ``set_noise_rules``, and the live counts run in the
``officina-noise`` worker. The case's own rules moved into "Filtri del
confronto" → "Regole avanzate" (phase 2.5, U4): ``test_officina_filters``.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QDialog

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import NoiseRule
from qtrequestory.ui.pages.officina_noise import DEBOUNCE_MS, SPINNER, NoiseDialog, hits_text
from qtrequestory.ui.pages.officina_noise_page import NOISE_JOB
from qtrequestory.ui.pages.officina_format import case_title
from tests.fakes.fake_core import fake_diff
from tests.ui.test_officina_page import open_case, page, shell, wait_idle  # noqa: F401 - fixtures

PRESETS = [NoiseRule("Data", r"\d{2}/\d{2}/\d{4}", False), NoiseRule("CAP", r"\b\d{5}\b", False)]
SLOW = "espressione potenzialmente troppo lenta: semplificala"


class _Signals(QObject):
    result = Signal(object)
    error = Signal(str, str)
    finished = Signal()


class _Job:
    def __init__(self) -> None:
        self.signals = _Signals()


class Counter:
    """Records each count request; the test answers it with :meth:`answer`."""

    def __init__(self) -> None:
        self.calls: list[list[NoiseRule]] = []
        self.jobs: list[_Job] = []

    def __call__(self, rules):
        self.calls.append(list(rules))
        self.jobs.append(_Job())
        return self.jobs[-1]

    def answer(self, hits: dict) -> None:
        self.jobs[-1].signals.result.emit(hits)


def dialog(qtbot, own=(), *, inherited=None, reserved=None, counter=None) -> NoiseDialog:
    d = NoiseDialog("Regole", list(own), own_title=strings.RUMORE_OWN_CASE, presets=PRESETS,
                    inherited=inherited or (), reserved=reserved, counter=counter)
    qtbot.addWidget(d)
    return d


def test_only_the_own_rules_no_presets_no_switches_and_rules_round_trip(qtbot):
    """Ruling F14: names and patterns only; a rule keeps its ``enabled``."""
    d = dialog(qtbot, [NoiseRule("Pratica", r"PR-\d{6}", False)])
    assert d.rules() == [NoiseRule("Pratica", r"PR-\d{6}", False)]
    assert not hasattr(d.editor, "presets") and not hasattr(d.editor, "active_presets")
    flags = d.own.item(0, 0).flags()
    assert not flags & flags.ItemIsUserCheckable, "no switch: the Filtri own it (F4)"
    d.add_rule("Nuova", "x")
    assert d.rules()[-1].enabled, "a new rule's default is on"
    assert strings.RUMORE_HELP.startswith("Le regole cercano nel testo normalizzato")
    assert "\n" not in strings.RUMORE_HELP, "one short line"


def test_a_bad_regex_blocks_ok_and_shows_the_error_only_on_its_row(qtbot):
    counter = Counter()
    d = dialog(qtbot, [NoiseRule("Pratica", r"PR-\d{6}")], counter=counter)
    bad = d.add_rule("Rotta", "(a+")
    good = d.own_row("Pratica")
    assert not d.ok_button.isEnabled() and d.blocked.isVisibleTo(d)
    assert d.hits_shown(bad).startswith("espressione non valida:")
    assert d.row_error(good) == "", "the other row is fine"
    qtbot.wait(DEBOUNCE_MS + 100)
    assert "Rotta" not in {r.name for r in counter.calls[-1]}, "a rule that does not compile is not sent"
    counter.answer({"Data": 0, "CAP": 1, "Pratica": 2})
    assert d.hits_shown(good) == strings.RUMORE_HITS_MANY.format(n=2)
    d.set_pattern(bad, "(a+)")
    assert d.ok_button.isEnabled() and not d.blocked.isVisibleTo(d)


def test_counts_refresh_on_edit_debounced_with_a_spinner(qtbot):
    counter = Counter()
    d = dialog(qtbot, [NoiseRule("Pratica", "PR")], counter=counter)
    qtbot.waitUntil(lambda: len(counter.calls) == 1, timeout=2000)
    counter.answer({"Data": 0, "CAP": 3, "Pratica": 1})
    assert d.hits_shown(0) == strings.RUMORE_HITS_ONE
    row = d.own_row("Pratica")
    for pattern in ("PR-", "PR-\\d", "PR-\\d{6}"):   # typing: one request after the pause
        d.set_pattern(row, pattern)
        qtbot.wait(DEBOUNCE_MS // 4)
    assert len(counter.calls) == 1, "nothing asked while the user types"
    qtbot.waitUntil(lambda: len(counter.calls) == 2, timeout=2000)
    sent = {r.name: r for r in counter.calls[-1]}
    assert sent["Pratica"].pattern == "PR-\\d{6}"
    assert set(sent) == {"Pratica"} and all(r.enabled for r in sent.values()), "only the own rules, as if on"
    assert d.hits_shown(row) in SPINNER, "a spinner while the count runs"
    counter.answer({"Data": 0, "CAP": 3, "Pratica": 4})
    assert d.hits_shown(row) == strings.RUMORE_HITS_MANY.format(n=4)
    assert not d.is_counting()


def test_a_stale_answer_is_ignored(qtbot):
    counter = Counter()
    d = dialog(qtbot, [NoiseRule("Pratica", "PR")], counter=counter)
    qtbot.waitUntil(lambda: len(counter.calls) == 1, timeout=2000)
    first = counter.jobs[0]
    d.set_pattern(0, "PX")
    qtbot.waitUntil(lambda: len(counter.calls) == 2, timeout=2000)
    first.signals.result.emit({"Data": 0, "CAP": 0, "Pratica": 9})
    assert d.hits_shown(0) in SPINNER


def test_the_services_slow_regex_error_is_shown_on_its_row_and_blocks_ok(qtbot):
    counter = Counter()
    d = dialog(qtbot, [NoiseRule("Lenta", "(a+)+b"), NoiseRule("Pratica", "PR")], counter=counter)
    qtbot.waitUntil(lambda: len(counter.calls) == 1, timeout=2000)
    counter.answer({"Data": 0, "CAP": 0, "Lenta": SLOW, "Pratica": 2})
    assert d.hits_shown(d.own_row("Lenta")) == SLOW
    assert d.row_error(d.own_row("Pratica")) == ""
    assert not d.ok_button.isEnabled()
    d.set_pattern(d.own_row("Lenta"), "a+b")
    assert d.ok_button.isEnabled(), "a new pattern is not the one the service refused"


def test_names_are_unique_across_presets_initiative_and_other_cases(qtbot):
    d = dialog(qtbot, inherited=[NoiseRule("Codice", "C-\\d+")],
               reserved={"Altro": strings.RUMORE_WHERE_CASE.format(case="MOD_TEST_B")})
    for name, where in (("Codice", strings.RUMORE_WHERE_INITIATIVE), ("CAP", strings.RUMORE_WHERE_PRESET),
                        ("Altro", strings.RUMORE_WHERE_CASE.format(case="MOD_TEST_B"))):
        row = d.add_rule(name, "x")
        assert d.row_error(row) == strings.RUMORE_ERR_DUPLICATE.format(where=where)
        assert not d.ok_button.isEnabled()
        d.own.removeRow(row)
        d._on_edited()
    first, second = d.add_rule("Mia", "x"), d.add_rule("Mia", "y")
    assert d.row_error(second) == strings.RUMORE_ERR_DUPLICATE.format(where=strings.RUMORE_WHERE_HERE)
    assert d.hits_shown(first) == d.row_error(first) != ""
    d.own.item(second, 0).setText("Mia 2")
    assert d.ok_button.isEnabled()


def test_the_add_button_names_the_new_rule_and_empty_fields_are_errors(qtbot):
    d = dialog(qtbot)
    d.add_button.click()
    assert d.rules()[0].name == strings.RUMORE_NEW_NAME.format(n=1)
    assert d.row_error(0) == strings.RUMORE_ERR_PATTERN_EMPTY
    d.own.item(0, 0).setText("  ")
    assert d.row_error(0) == strings.RUMORE_ERR_NAME_EMPTY


def test_without_a_case_there_is_nothing_to_count(qtbot):
    d = dialog(qtbot, [NoiseRule("Pratica", "PR")])
    qtbot.wait(DEBOUNCE_MS + 100)
    assert d.hits_shown(0) == strings.RUMORE_HITS_UNKNOWN
    assert hits_text(0) == strings.RUMORE_HITS_NONE and hits_text(1) == strings.RUMORE_HITS_ONE


# ------------------------------------------------------------ from the page ---

class _Answering(NoiseDialog):
    """The real dialog, answered at once: it adds one rule."""

    rule = NoiseRule("Pratica", r"PR-\d{6}")
    last: NoiseDialog | None = None
    seen: dict = {}
    deleted: list = []

    def exec(self) -> int:
        type(self).last = self
        self.add_rule(self.rule.name, self.rule.pattern)
        # what the test looks at afterwards (the page deletes the dialog once it is answered)
        type(self).seen = {"hits": self.hits_shown(0), "error": self.row_error(0)}
        self.destroyed.connect(lambda *_a: type(self).deleted.append(True))
        return QDialog.DialogCode.Accepted if self.ok_button.isEnabled() else QDialog.DialogCode.Rejected


def _judged_case(qtbot, page, fake_core, tmp_path):
    case = open_case(page, fake_core, tmp_path)
    fake_core.officina.generate(page.ini, case, "tobe")
    page.refresh()
    fake_core.officina.set_canned(case.id, 1, [fake_diff("cambiato", "testo", "12,00", "11,00")])
    page.open_case(case.id)
    qtbot.waitUntil(lambda: page.case_view.docs is not None and page.case_view.docs.judged is not None,
                    timeout=10000)
    qtbot.waitUntil(lambda: not page.case_view.judging, timeout=10000)
    return page._case(case.id)


def test_the_board_saves_the_initiative_rules(qtbot, page, fake_core, tmp_path, monkeypatch):
    _judged_case(qtbot, page, fake_core, tmp_path)
    page.show_board()
    monkeypatch.setattr(type(page), "noise_dialog", _Answering)
    page.board.noise_button.click()
    reloaded = fake_core.officina.load(page.ini.id)
    assert reloaded.noise_rules == [_Answering.rule]
    assert reloaded.filters == {}, "F14: no preset or switch changed here"
    assert _Answering.seen["hits"] == strings.RUMORE_HITS_UNKNOWN, "no case selected: nothing to count on"


def test_a_name_used_by_a_case_is_refused_on_the_board(qtbot, page, fake_core, tmp_path, monkeypatch):
    case = _judged_case(qtbot, page, fake_core, tmp_path)
    fake_core.officina.set_noise_rules(page.ini, case, [_Answering.rule])
    page.refresh()
    page.show_board()
    monkeypatch.setattr(type(page), "noise_dialog", _Answering)
    page.board.noise_button.click()
    assert _Answering.seen["error"] == strings.RUMORE_ERR_DUPLICATE.format(
        where=strings.RUMORE_WHERE_CASE.format(case=case_title(case)))
    assert fake_core.officina.load(page.ini.id).noise_rules == [], "nothing saved"


def test_live_counts_run_in_the_noise_worker(qtbot, page, fake_core, runner, tmp_path):
    case = _judged_case(qtbot, page, fake_core, tmp_path)
    fake_core.officina.set_noise_text(case.id, "PR-123456 e PR-654321 del 01/02/2026")
    d = NoiseDialog("Regole", [NoiseRule("Pratica", r"PR-\d{6}")], own_title=strings.RUMORE_OWN_CASE,
                    presets=fake_core.officina.noise_presets(), counter=page._counter(case))
    qtbot.addWidget(d)
    qtbot.waitUntil(lambda: runner.job(NOISE_JOB) is not None, timeout=3000)
    qtbot.waitUntil(lambda: d.hits_shown(0) == strings.RUMORE_HITS_MANY.format(n=2), timeout=10000)
    wait_idle(qtbot, page)


def test_the_board_counts_on_the_selected_case(qtbot, page, fake_core, tmp_path, monkeypatch):
    case = _judged_case(qtbot, page, fake_core, tmp_path)
    fake_core.officina.set_noise_text(case.id, "PR-123456")
    page.show_board()
    page.board.select_cases([case.id])
    seen = []

    class _Look(NoiseDialog):
        def exec(self) -> int:
            seen.append(self)
            return QDialog.DialogCode.Rejected

    monkeypatch.setattr(type(page), "noise_dialog", _Look)
    page.board.noise_button.click()
    assert seen and seen[0]._counter is not None


def test_the_board_dialog_waits_for_the_generations(qtbot, page, fake_core, tmp_path, monkeypatch):
    _judged_case(qtbot, page, fake_core, tmp_path)
    page.show_board()
    monkeypatch.setattr(page.queue, "is_busy", lambda: True)
    opened = []
    monkeypatch.setattr(type(page), "noise_dialog", lambda *a, **k: opened.append(a))
    page.board.noise_button.click()
    assert not opened and strings.RUMORE_WAIT_GENERATION in page._window.statuses


def test_changing_the_rules_needs_no_board_summary_job(qtbot, page, fake_core, tmp_path, monkeypatch):
    """The board reads the saved summaries (U5): saving the initiative's
    rules reloads it, nothing to forget (the U6 call to the removed
    ``Board.forget_summary`` is gone)."""
    _judged_case(qtbot, page, fake_core, tmp_path)
    page.show_board()
    monkeypatch.setattr(type(page), "noise_dialog", _Answering)
    page.board.noise_button.click()
    assert ("set_noise_rules", None) in fake_core.officina.review_actions
    assert (strings.RUMORE_SAVED_INITIATIVE, "ok") in page._window.toasts


def test_a_closed_dialog_stops_counting(qtbot):
    counter = Counter()
    d = dialog(qtbot, [NoiseRule("Pratica", "PR")], counter=counter)
    qtbot.waitUntil(lambda: len(counter.calls) == 1, timeout=2000)
    d.reject()
    counter.answer({"Data": 0, "CAP": 0, "Pratica": 9})   # late: ignored
    d.set_pattern(0, "PX")
    qtbot.wait(DEBOUNCE_MS + 100)
    assert len(counter.calls) == 1 and d.hits_shown(0) != strings.RUMORE_HITS_MANY.format(n=9)


def test_a_pattern_that_overflows_or_nests_too_deep_is_a_row_error_not_a_crash(qtbot):
    """Re-review m1: re.compile can raise OverflowError and RecursionError too."""
    d = dialog(qtbot)
    huge = d.add_rule("Enorme", "a{4294967296}")
    deep = d.add_rule("Profonda", "(" * 2000 + "a" + ")" * 2000)
    for row in (huge, deep):
        assert d.row_error(row).startswith("espressione non valida:")
    assert not d.ok_button.isEnabled()


def test_the_board_cannot_change_presets_or_switches(qtbot, page, fake_core, tmp_path, monkeypatch):
    """Ruling F14: the initiative's presets and the defaults of every switch
    come only from "Filtri del confronto"; the board dialog saves the rules
    and leaves ``filtri`` exactly as they were."""
    _judged_case(qtbot, page, fake_core, tmp_path)
    api = fake_core.officina
    api.set_filters(page.ini, None, {"avanzate.Data": True, "zona.footer": True})
    page.refresh()
    page.show_board()
    before = api.load(page.ini.id)
    calls = []
    real = api.set_noise_rules

    def spy(ini, where, rules, presets=None):
        calls.append(presets)
        real(ini, where, rules, presets)

    monkeypatch.setattr(api, "set_noise_rules", spy)
    monkeypatch.setattr(type(page), "noise_dialog", _Answering)
    page.board.noise_button.click()
    after = api.load(page.ini.id)
    assert calls == [None], "the presets argument is never passed"
    assert after.filters == before.filters == {"avanzate.Data": True, "zona.footer": True}
    assert after.noise_rules == [_Answering.rule]
