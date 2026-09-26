"""Officina phase 2 end to end on the REAL engine (task I1).

The case view driven by the real ``OfficinaService`` (engine, review state,
``caso.json``) behind the page, with the local ``FakeServer`` as the document
generator — never a real endpoint. The rest of the bundle is the fake core.

PDF case: create the case, AS-IS, v1, mark two differences with F from the
list, v2 fixes one of them: the verification strip says "1 risolta, 1 non
risolta" and the stuck one is flagged in the list. HTML case: the same page
with the real Edge print (skipped without Edge). Synthetic data only.
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from qtrequestory.core.config import GeneratorEndpoint
from qtrequestory.officina.compare.edge import find_edge
from qtrequestory.officina.service import OfficinaService
from qtrequestory.ui import strings
from qtrequestory.ui.pages.officina_page import OfficinaPage
from qtrequestory.ui.pages.officina_verdict_style import flagged
from tests.fakes.fake_core import build_fake_core, canned_pdf
from tests.officina.test_generator import FakeServer
from tests.ui.test_officina_page import FakeWindow, wait_idle

TARGET = ["Contratto di prova per Acme-Servizi", "Il prezzo resta fisso per dodici mesi",
          "La carta sarà abilitata agli acquisti online", "Pagamento con addebito mensile anticipato",
          "Firma del cliente in calce al modulo"]
PAYLOAD = {"documents": [{"template": {"templateKey": "MOD_TEST_A"},
                          "attributes": [{"key": "attachmentId", "value": "att-0"},
                                         {"key": "attachmentUrl",
                                          "value": "https://example.invalid/c/MOD_TEST_A.pdf"}]}],
           "customers": [{"name": "Cliente di prova"}]}


def doc(*changes: tuple[str, str]) -> bytes:
    lines = list(TARGET)
    for old, new in changes:
        lines = [line.replace(old, new) for line in lines]
    return canned_pdf("\n".join(lines))


@pytest.fixture
def server():
    s = FakeServer()
    yield s
    s.close()


@pytest.fixture
def real(tmp_path: Path, server: FakeServer):
    """The fake bundle with the REAL Officina service, generator = local server."""
    bundle = build_fake_core(tmp_path / "core")
    cfg = bundle.config.config
    bundle.config.config = dataclasses.replace(cfg, officina=dataclasses.replace(
        cfg.officina, generators=[GeneratorEndpoint("svil", server.url)], default_generator="svil"))
    service = OfficinaService(lambda: bundle.config.config)
    return dataclasses.replace(bundle, officina_factory=lambda: service)


def _case(real, tmp_path: Path, target: bytes, name: str):
    api = real.officina
    ini = api.create_initiative("Banco reale")
    src = tmp_path / "payload.json"
    src.write_text(json.dumps(PAYLOAD), encoding="utf-8")
    case = api.case_from_file(ini, src, "MOD_TEST_A")
    target_file = tmp_path / name
    target_file.write_bytes(target)
    api.set_target(case, target_file)
    return ini, case


def _page(qtbot, real, runner, ini, case) -> OfficinaPage:
    page = OfficinaPage(real, runner, FakeWindow())
    qtbot.addWidget(page)
    page.resize(1366, 768)
    page.show()
    page.refresh()
    page.open_initiative(ini.name)
    page.open_case(case.id)
    return page


def _generate(qtbot, page: OfficinaPage, server: FakeServer, body: bytes, *, asis: bool = False,
              version: int | None = None) -> None:
    server.canned.status, server.canned.body = 200, body
    (page.case_view.asis_button if asis else page.case_view.regenerate_button).click()
    wait_idle(qtbot, page)
    if version is not None:
        qtbot.waitUntil(lambda: page.case_view.docs is not None and page.case_view.docs.judged is not None
                        and page.case_view.docs.judged.version == version
                        and not page.case_view.judging, timeout=30000)


def _press_f(qtbot, page: OfficinaPage, target_text: str) -> None:
    j = next(x for x in page.case_view.docs.judged.judged if x.diff.left_text == target_text)
    page.case_view.diffs.select(j.diff.id)
    page.case_view.diffs.trigger("fatta")
    qtbot.waitUntil(lambda: not page.case_view.acting and not page.review_queue.get((page.ini.id, page.case_id)),
                    timeout=30000)


def test_mark_two_and_regenerate_verifies_them_on_the_real_engine(qtbot, real, runner, server, tmp_path):
    ini, case = _case(real, tmp_path, canned_pdf("\n".join(TARGET)), "atteso.pdf")
    page = _page(qtbot, real, runner, ini, case)
    _generate(qtbot, page, server, doc(("dodici", "ventiquattro"), ("abilitata", "abilitato"),
                                       ("mensile", "trimestrale")), asis=True)
    _generate(qtbot, page, server, doc(("dodici", "ventiquattro"), ("abilitata", "abilitato")), version=1)
    view = page.case_view
    verdicts = {j.diff.left_text: j.verdict for j in view.docs.judged.judged}
    assert verdicts == {"dodici": "da_fare", "abilitata": "da_fare", "mensile": "fatta"}

    _press_f(qtbot, page, "dodici")
    _press_f(qtbot, page, "abilitata")
    env = page._case(case.id).env
    assert view.banners.marks_text() == strings.REVISIONE_MARKS_MANY.format(n=2, env=env)
    assert view.docs.judged.summary.da_verificare == 2

    _generate(qtbot, page, server, doc(("abilitata", "abilitato")), version=2)  # v2 fixes "dodici"
    assert view.banners.outcome_text() == "v2: verificate 2 modifiche segnate — 1 risolta, 1 non risolta"
    assert view.banners.marks_text() == "", "the verified marks are gone"
    stuck = next(j for j in view.docs.judged.judged if j.diff.left_text == "abilitata")
    assert stuck.verdict == "da_fare" and flagged(stuck)
    assert strings.ELENCO_NON_RISOLTA.format(n=1, m=2) in view.diffs.texts()[0], "on top, with its reason"
    on_disk = next(c for c in real.officina.load(ini.id).cases if c.id == case.id)
    assert on_disk.review.marks == [] and [v for _a, v, _g in on_disk.review.unresolved] == [1]
    assert on_disk.review.summary is not None and on_disk.review.summary.version == 2


T_HTML = ('<html><body><table><tr><td><p>Gentile cliente, la sua offerta è attiva.</p>'
          '<p>Leggi le <a href="https://example.invalid/condizioni?id=1">condizioni</a> del servizio.</p>'
          '<p>Il prezzo resta fisso per dodici mesi.</p></td></tr></table>'
          + '<p>Questa email di prova è inviata da Acme-Servizi a un indirizzo example.invalid.</p>' * 8
          + '</body></html>')
G_HTML = T_HTML.replace("dodici", "ventiquattro").replace("condizioni?id=1", "condizioni?id=2")


@pytest.mark.skipif(find_edge() is None, reason="Microsoft Edge non installato")
def test_an_html_case_is_judged_through_its_dom_with_the_edge_print(qtbot, real, runner, server, tmp_path):
    ini, case = _case(real, tmp_path, T_HTML.encode(), "email.html")
    page = _page(qtbot, real, runner, ini, case)
    _generate(qtbot, page, server, G_HTML.encode(), version=1)
    view = page.case_view
    judged = view.docs.judged.judged
    changed = next(j for j in judged if j.diff.klass == "testo")
    assert (changed.diff.left_text, changed.diff.right_text) == ("dodici", "ventiquattro")
    assert changed.diff.left and changed.diff.right, "boxed from the Edge print"
    link = next(j for j in judged if j.diff.klass == "link")
    # the DOM tab on the engine's pretty sources (U6 was built on the fake's raw HTML)
    assert view.dom_available()
    view.set_dom_mode(True)
    qtbot.waitUntil(lambda: view.dom.key is not None, timeout=30000)
    view.diffs.select(link.diff.id)
    left_line, right_line = view.dom.line_of(link.diff.id)
    assert left_line is not None and right_line is not None, "the link diff has its DOM lines"


def test_an_html_case_without_edge_is_judged_through_the_dom(qtbot, tmp_path, server, runner):
    """R45 (spec §6): without Edge the case view does not stop at the print
    error: compare_case compares the DOM, the viewers say the print is not
    available, the DOM tab becomes the main view, the list and verdicts work."""
    bundle = build_fake_core(tmp_path / "core")
    cfg = bundle.config.config
    bundle.config.config = dataclasses.replace(cfg, officina=dataclasses.replace(
        cfg.officina, generators=[GeneratorEndpoint("svil", server.url)], default_generator="svil"))
    service = OfficinaService(lambda: bundle.config.config, html_to_pdf=lambda *a, **k: "Edge non trovato")
    real = dataclasses.replace(bundle, officina_factory=lambda: service)
    ini, case = _case(real, tmp_path, T_HTML.encode(), "email.html")
    page = _page(qtbot, real, runner, ini, case)
    _generate(qtbot, page, server, G_HTML.encode(), version=1)
    view = page.case_view
    judged = view.docs.judged.judged
    assert ("testo", "dodici", "ventiquattro") in [(j.diff.klass, j.diff.left_text, j.diff.right_text)
                                                  for j in judged]
    assert any(j.diff.klass == "link" for j in judged)
    for side in (view.left, view.right):
        assert side.message_text().startswith(strings.OFFICINA_PRINT_MISSING.split("{")[0])
    assert view.dom_mode(), "the DOM tab is the main view"
    qtbot.waitUntil(lambda: view.dom.key is not None, timeout=30000)
    assert view.diffs.row_ids(), "the list works"


def test_azzera_tolleranze_clears_them_on_the_real_service(qtbot, real, runner, server, tmp_path,
                                                          monkeypatch):
    """R45 (spec §5.2): "Azzera tolleranze…" in the case's "⋯" menu asks
    (the question says what goes and that it cannot be undone), then
    reset_tolerances and the same version is judged again."""
    from qtrequestory.ui.pages import officina_dialogs

    ini, case = _case(real, tmp_path, canned_pdf("\n".join(TARGET)), "atteso.pdf")
    page = _page(qtbot, real, runner, ini, case)
    _generate(qtbot, page, server, doc(("dodici", "ventiquattro")), version=1)
    view = page.case_view
    j = next(x for x in view.docs.judged.judged if x.diff.left_text == "dodici")
    real.officina.tolerate(page._case(case.id), j, "va bene")
    page.open_case(case.id, "v1")
    qtbot.waitUntil(lambda: view.docs is not None and view.docs.judged is not None and not view.judging
                    and view.docs.judged.judged[0].verdict == "tollerata", timeout=30000)
    asked: list[str] = []
    monkeypatch.setattr(officina_dialogs, "confirm", lambda _p, _t, text: asked.append(text) or False)
    view.reset_tolerances_action.trigger()
    assert asked == [strings.OFFICINA_RESET_TOLERANCES_CONFIRM]
    assert real.officina.load(ini.id).cases[0].review.tolerances, "No: nothing changed"
    monkeypatch.setattr(officina_dialogs, "confirm", lambda *_a: True)
    view.reset_tolerances_action.trigger()
    qtbot.waitUntil(lambda: view.docs is not None and view.docs.judged is not None and not view.judging
                    and view.docs.judged.judged[0].verdict == "da_fare", timeout=30000)
    assert real.officina.load(ini.id).cases[0].review.tolerances == []


def test_mostra_fatte_shows_the_fatte_on_the_target_side(qtbot, real, runner, server, tmp_path):
    """R45 (spec §7.1): a checkable "Mostra fatte" next to the list tabs; the
    fatte are then drawn (target side) and in the minimap; opening the
    "Fatte" tab turns it on."""
    ini, case = _case(real, tmp_path, canned_pdf("\n".join(TARGET)), "atteso.pdf")
    page = _page(qtbot, real, runner, ini, case)
    _generate(qtbot, page, server, doc(("dodici", "ventiquattro"), ("mensile", "trimestrale")), asis=True)
    _generate(qtbot, page, server, doc(("dodici", "ventiquattro")), version=1)  # "mensile" is fatta
    view = page.case_view
    fatta = next(j for j in view.docs.judged.judged if j.verdict == "fatta")
    assert not view.done_button.isChecked() and not view.left.view.show_done()
    assert fatta.diff.id not in {s.diff_id for s in view.left.view.minimap.segments()}
    view.done_button.click()
    assert view.left.view.show_done()
    assert fatta.diff.id in {s.diff_id for s in view.left.view.minimap.segments()}
    view.done_button.click()
    assert not view.left.view.show_done()
    view.diffs.tab_buttons["fatte"].click()
    assert view.done_button.isChecked() and view.left.view.show_done()
