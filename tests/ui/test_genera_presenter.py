"""GeneraPresenter: the Genera tab's state, its problems and the request it builds.

No widget here: the presenter is driven through its methods on the fake core
(generator ``svil``; log environments ``coll`` and ``svil``). Synthetic data
only (``MOD_TEST_*``, FDI ``aaaaaaaa-1111-…``).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from qtrequestory.ui import prefs, strings
from qtrequestory.ui.actions import user_settings
from qtrequestory.ui.contracts import NO_PACKAGE, BatchReport, Outcome, Target
from qtrequestory.ui.pages.genera_presenter import CONFIRM_ABOVE, GeneraPresenter

FDI_A = "aaaaaaaa-1111-4222-8333-444444444444"
FDI_B = "bbbbbbbb-1111-4222-8333-444444444444"


def _elenco(tmp_path: Path) -> Path:
    path = tmp_path / "elenco.csv"
    path.write_bytes(("Template key;Nome Template ICM;Nome iniziativa;codice iniziativa ;package name\r\n"
                      "MOD_TEST_A;;;;111_PKG\r\n"
                      "MOD_TEST_B;;;;111_PKG\r\n"
                      "MOD_TEST_B;;;;222_PKG\r\n"
                      "MOD_TEST_C;;;;222_PKG\r\n"
                      ";;;;333_PKG\r\n").encode("cp1252"))
    return path


@pytest.fixture
def presenter(qapp, fake_core, tmp_path: Path) -> GeneraPresenter:
    p = GeneraPresenter(fake_core)
    p.activate()  # what the page does when the tab is first shown
    p.set_destination(tmp_path / "dest")
    return p


def _outcome(key: str, status: str, folders=(NO_PACKAGE,), fdi: str | None = None) -> Outcome:
    return Outcome(key=key, folders=tuple(folders), fdi=fdi, status=status, doc_type=None, files=(),
                   duration_ms=0, http_status=None, reason="")


# -- problems ------------------------------------------------------------------------

def test_no_destination_is_a_problem(presenter):
    presenter.set_keys_text("MOD_TEST_A")
    assert presenter.problems() == []
    presenter.set_destination(None)
    assert presenter.problems() == [strings.GENERA_NEED_DESTINATION]


def test_no_keys_is_a_problem(presenter):
    assert presenter.problems() == [strings.GENERA_NEED_KEYS]
    presenter.set_keys_text("  ,; \n ")
    assert presenter.problems() == [strings.GENERA_NEED_KEYS]
    presenter.set_keys_text("MOD_TEST_A")
    assert presenter.problems() == []


def test_the_first_problem_is_the_one_highest_on_the_screen(presenter):
    presenter.set_destination(None)
    assert presenter.problems()[0] == strings.GENERA_NEED_KEYS  # "cosa" comes before "dove"


def test_elenco_mode_needs_a_list_then_a_package(presenter, tmp_path):
    presenter.set_mode("elenco")
    assert presenter.problems() == [strings.GENERA_NEED_ELENCO]
    assert presenter.load_elenco(_elenco(tmp_path))
    assert presenter.problems() == [strings.GENERA_NEED_PACKAGE]


def test_invalid_header_row_is_a_problem(presenter):
    presenter.set_keys_text("MOD_TEST_A")
    rows = presenter.header_rows
    presenter.set_header_rows([*rows, ("IMEL", "riga\nspezzata")])
    (problem,) = presenter.problems()
    assert problem.startswith("Header: ") and "IMEL" in problem
    assert presenter.header_row_problems()[-1]
    presenter.set_header_rows([*rows, ("Content-Length", "1")])
    assert presenter.problems()[0].startswith("Header: ")
    presenter.reset_headers()
    assert presenter.problems() == []


def test_no_generator_means_no_generator(qapp, fake_core):
    cfg = fake_core.config.config
    cfg.officina.generators = []
    presenter = GeneraPresenter(fake_core)
    assert not presenter.has_generator()
    presenter.set_keys_text("MOD_TEST_A")
    # what the line under the button says when the form stays on screen (a run's results)
    assert presenter.problems()[0] == strings.GENERA_NEED_GENERATOR


# -- targets ---------------------------------------------------------------------------

def test_keys_mode_builds_targets_with_elenco_packages(presenter, tmp_path):
    presenter.set_keys_text("mod_test_b, MOD_TEST_Z")
    assert presenter.targets() == (Target("key", "mod_test_b", (NO_PACKAGE,)),
                                   Target("key", "MOD_TEST_Z", (NO_PACKAGE,)))
    presenter.load_elenco(_elenco(tmp_path))  # loaded in the Elenco mode: the keys use it too
    assert presenter.mode == "keys"
    assert presenter.targets() == (Target("key", "mod_test_b", ("111_PKG", "222_PKG")),
                                   Target("key", "MOD_TEST_Z", (NO_PACKAGE,)))
    request = presenter.build_request()
    assert (request.generator, request.source_env) == ("svil", "svil")
    assert request.destination == tmp_path / "dest"
    assert request.header_rows == tuple(presenter.header_rows)
    assert (request.save_html, request.make_zip) == (False, False)
    assert request.fallback_envs == ("coll",)  # a key refused or missing in svil tries coll


def test_fallback_envs_put_the_generator_logs_first(presenter):
    presenter.set_source_env("coll")
    assert presenter.build_request().fallback_envs == ("svil",)


def test_elenco_mode_uses_only_checked_packages(presenter, tmp_path):
    presenter.set_mode("elenco")
    presenter.load_elenco(_elenco(tmp_path))
    presenter.set_package_checked("222_PKG", True)
    assert presenter.targets() == (Target("key", "MOD_TEST_B", ("222_PKG",)),
                                   Target("key", "MOD_TEST_C", ("222_PKG",)))
    presenter.set_packages_checked(["111_PKG", "222_PKG"], True)
    assert [t.value for t in presenter.targets()] == ["MOD_TEST_A", "MOD_TEST_B", "MOD_TEST_C"]
    presenter.set_packages_checked(["111_PKG", "222_PKG"], False)
    assert presenter.targets() == ()
    assert presenter.elenco_skipped_note() == strings.GENERA_ELENCO_SKIPPED_ONE


def test_fdi_mode_builds_fdi_targets(presenter):
    presenter.set_mode("fdi")
    presenter.set_fdi_text(f"{FDI_A}\n{FDI_A.upper()}\n\n{FDI_B}  ")
    assert presenter.targets() == (Target("fdi", FDI_A, ()), Target("fdi", FDI_B, ()))
    assert presenter.problems() == []


def test_a_failed_list_is_said_and_not_remembered(presenter, tmp_path):
    assert not presenter.load_elenco(tmp_path / "assente.csv")
    assert presenter.elenco is None and presenter.elenco_error
    assert user_settings().value(prefs.GENERA_ELENCO_KEY) in (None, "")


# -- environments ----------------------------------------------------------------------

def test_source_env_follows_generator_until_changed(qapp, fake_core):
    cfg = fake_core.config.config
    from qtrequestory.ui.contracts import GeneratorEndpoint

    cfg.officina.generators = [GeneratorEndpoint("svil", "https://example.invalid/svil"),
                               GeneratorEndpoint("coll", "https://example.invalid/coll")]
    presenter = GeneraPresenter(fake_core)
    assert presenter.generators == ["svil", "coll"]
    assert (presenter.generator, presenter.source_env) == ("svil", "svil")
    presenter.set_generator("coll")
    assert presenter.source_env == "coll"  # follows
    presenter.set_source_env("svil")       # the user's choice: coll's payloads... from svil
    presenter.set_generator("svil")
    presenter.set_generator("coll")
    assert presenter.source_env == "svil"  # no longer follows
    presenter.set_source_env("coll")       # the same as the generator again: follows again
    presenter.set_generator("svil")
    assert presenter.source_env == "svil"


# -- counts and wording ----------------------------------------------------------------------

def test_call_count_per_mode(presenter, tmp_path):
    presenter.set_keys_text("MOD_TEST_A mod_test_a MOD_TEST_B")
    assert presenter.call_count() == 2
    assert presenter.start_text() == strings.GENERA_START_N.format(n=2)
    presenter.set_keys_text("MOD_TEST_A")
    assert presenter.start_text() == strings.GENERA_START_ONE
    presenter.set_mode("elenco")
    assert presenter.call_count() == 0 and presenter.start_text() == strings.GENERA_START
    presenter.load_elenco(_elenco(tmp_path))
    presenter.set_packages_checked(["111_PKG", "222_PKG"], True)
    assert presenter.call_count() == 3
    presenter.set_mode("fdi")
    presenter.set_fdi_text(f"{FDI_A}\n{FDI_B}")
    assert presenter.call_count() == 2
    assert presenter.start_text() == strings.GENERA_START_FDI.format(n=2)
    presenter.set_mode("keys")  # each mode keeps its own text
    assert presenter.call_count() == 1


def test_confirmation_only_over_the_threshold(presenter):
    presenter.set_keys_text(" ".join(f"MOD_TEST_{i}" for i in range(CONFIRM_ABOVE)))
    assert not presenter.needs_confirmation()
    presenter.set_keys_text(" ".join(f"MOD_TEST_{i}" for i in range(CONFIRM_ABOVE + 1)))
    assert presenter.needs_confirmation()
    title, text = presenter.confirmation()
    assert str(CONFIRM_ABOVE + 1) in title and "svil" in text
    assert not presenter.needs_count(presenter.build_request())  # one call per key: known


def test_fdis_are_counted_in_calls_not_fdis(presenter):
    """Review item 6: 15 FDIs × 10 keys are 150 calls, not 15."""
    presenter.set_mode("fdi")
    presenter.set_fdi_text(f"{FDI_A}\n{FDI_B}")
    request = presenter.build_request()
    assert presenter.needs_count(request)
    assert presenter.needs_confirmation(150)
    title, text = presenter.confirmation(request, 150)
    assert "150" in title and "150" in text and "2 FDI" in text


def test_headers_summary_counts_the_changes(presenter):
    rows = presenter.header_rows
    n = len(rows)
    assert presenter.headers_summary() == strings.GENERA_HEADERS_SUMMARY.format(n=n)
    presenter.set_header_rows([*rows, ("IMEL", "active")])
    assert presenter.headers_summary() == strings.GENERA_HEADERS_SUMMARY_MODIFIED_ONE.format(n=n + 1)
    presenter.set_header_rows(rows[1:] + [("IMEL", "active")])  # one removed, one added
    assert presenter.headers_summary() == strings.GENERA_HEADERS_SUMMARY_MODIFIED.format(n=n, m=2)


# -- retry -----------------------------------------------------------------------------------

def test_retry_request_keeps_only_unfinished(presenter, tmp_path):
    presenter.set_keys_text("MOD_TEST_A")
    report = BatchReport(run_dir=tmp_path / "dest" / "svil_x", zips=(), cancelled=True, outcomes=(
        _outcome("MOD_TEST_A", "ok", fdi=FDI_A),
        _outcome("MOD_TEST_B", "failed", ("111_PKG", "222_PKG"), fdi=FDI_A),
        _outcome("MOD_TEST_C", "html_skipped"),
        _outcome("MOD_TEST_D", "no_call"),
        _outcome("MOD_TEST_E", "cancelled"),
        # two calls of one FDI target (an ok one between them) and an FDI that had none
        _outcome("MOD_TEST_F", "failed", (FDI_B,), fdi=FDI_B),
        _outcome("MOD_TEST_K", "ok", (FDI_B,), fdi=FDI_B),
        _outcome("MOD_TEST_G", "cancelled", (FDI_B,), fdi=FDI_B),
        _outcome("", "no_call", ("cccccccc-1111-4222-8333-444444444444",),
                 fdi="cccccccc-1111-4222-8333-444444444444"),
    ))
    request = presenter.retry_request(report)
    assert request.targets == (
        Target("key", "MOD_TEST_B", ("111_PKG", "222_PKG")),
        Target("key", "MOD_TEST_D", (NO_PACKAGE,)),
        Target("key", "MOD_TEST_E", (NO_PACKAGE,)),
        # review item 1: only F and G of FDI_B (its own calls), never K again
        Target("fdi", FDI_B, (), ("MOD_TEST_F", "MOD_TEST_G")),
        Target("fdi", "cccccccc-1111-4222-8333-444444444444", ()),  # no calls: the whole FDI
    )
    assert request.generator == "svil" and request.destination == tmp_path / "dest"
    assert presenter.retry_count(report) == 6  # = the calls the retry makes


# -- preferences ---------------------------------------------------------------------------

def test_choices_are_remembered_and_restored(qapp, fake_core, tmp_path):
    dest = tmp_path / "dest"
    dest.mkdir()
    first = GeneraPresenter(fake_core)
    first.set_destination(dest)
    first.set_mode("elenco")
    first.load_elenco(_elenco(tmp_path))
    first.set_source_env("coll")
    first.set_make_zip(True)
    first.set_save_html(True)
    again = GeneraPresenter(fake_core)
    assert (again.mode, again.destination, again.source_env) == ("elenco", dest, "coll")
    assert again.elenco is None  # read when the tab is first shown, not while the window is built
    again.activate()
    assert again.elenco is not None and again.elenco_path == tmp_path / "elenco.csv"
    assert (again.make_zip, again.save_html) == (True, True)


def test_a_vanished_folder_is_kept_and_a_vanished_list_dropped(qapp, fake_core, tmp_path):
    stored = user_settings()
    stored.setValue(prefs.GENERA_DESTINATION_KEY, str(tmp_path / "sparita"))
    stored.setValue(prefs.GENERA_ELENCO_KEY, str(tmp_path / "sparito.csv"))
    stored.setValue(prefs.GENERA_MODE_KEY, "boh")
    stored.setValue(prefs.GENERA_GENERATOR_KEY, "prod")
    presenter = GeneraPresenter(fake_core)
    presenter.activate()
    # review item 8: the folder is kept as text, unchecked (the run creates it, or says why not)
    assert presenter.destination == tmp_path / "sparita" and presenter.elenco is None
    assert presenter.elenco_error == ""  # nothing to report: it was only a memory
    assert (presenter.mode, presenter.generator) == ("keys", "svil")


def test_construction_touches_neither_the_disk_nor_the_service(qapp, fake_core, tmp_path,
                                                               monkeypatch):
    """Review item 8: no Officina service and no file read while the window is built."""
    import dataclasses

    officina = fake_core.officina
    built: list[int] = []
    services = dataclasses.replace(fake_core, officina_factory=lambda: built.append(1) or officina)
    stored = user_settings()
    stored.setValue(prefs.GENERA_ELENCO_KEY, str(_elenco(tmp_path)))
    stored.setValue(prefs.GENERA_DESTINATION_KEY, r"\\server-assente\condivisa\Genera")

    def no_disk(*_a, **_k):
        raise AssertionError("disk touched while the window is built")

    monkeypatch.setattr(Path, "is_dir", no_disk)
    monkeypatch.setattr(Path, "is_file", no_disk)
    monkeypatch.setattr(Path, "read_bytes", no_disk)
    presenter = GeneraPresenter(services)
    assert built == [] and presenter.elenco is None
    assert presenter.destination == Path(r"\\server-assente\condivisa\Genera")
    monkeypatch.undo()
    presenter.activate()
    assert built == [1] and presenter.elenco is not None and presenter.header_rows


def test_a_remembered_list_that_is_not_a_csv_never_breaks_the_tab(qapp, fake_core, tmp_path):
    """Review item 4: a remembered unparsable file made the tab unavailable at every start."""
    bad = tmp_path / "elenco.csv"
    bad.write_text('Template key;a;b;c;package name\n"MOD_A;x;y;z;PKG\n' + "x" * 200_000,
                   encoding="utf-8")
    user_settings().setValue(prefs.GENERA_ELENCO_KEY, str(bad))
    presenter = GeneraPresenter(fake_core)
    presenter.activate()
    assert presenter.elenco is None and presenter.elenco_error == ""


def test_an_unexpected_failure_reading_a_list_is_said_not_raised(presenter, fake_core, tmp_path,
                                                                 monkeypatch):
    def boom(_path):
        raise RuntimeError("guasto")

    monkeypatch.setattr(fake_core.officina, "batch_load_elenco", boom)
    assert not presenter.load_elenco(tmp_path / "elenco.csv")
    assert presenter.elenco_error == strings.GENERA_ELENCO_UNREADABLE
