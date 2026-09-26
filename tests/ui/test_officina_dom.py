"""Officina phase 2 (U6): the DOM tab of an HTML case (spec §6).

Where a difference sits in the pretty sources (``officina_dom_map``), then
the case view on the fake core: the "Documenti | DOM" switch only for an HTML
case, and the selection shared both ways between the list and the DOM lines.
"""
from __future__ import annotations

from PySide6.QtGui import QTextCursor

from qtrequestory.ui import strings
from qtrequestory.ui.pages.officina_dom_map import locate, node_at, parse
from tests.fakes.fake_core import fake_diff
from tests.ui.test_officina_page import open_case, page, shell  # noqa: F401 - fixtures

TARGET = """<!DOCTYPE html>
<html>
  <head>
    <title>
      Oggetto
    </title>
    <style>
      p{color:red}
    </style>
  </head>
  <body>
    <table>
      <tr>
        <td>
          Gentile cliente,
        </td>
        <td>
          <img src="https://example.invalid/logo.png" alt="Logo">
        </td>
      </tr>
    </table>
    <p>
      Per i dettagli
      <a href="https://Example.invalid/condizioni?utm_source=x">
        Scopri le
        <b>
          condizioni
        </b>
      </a>
      del servizio.
    </p>
    <div>
      Testo libero
      <ul>
        <li>
          Uno
        </li>
        <li>
          Due
        </li>
      </ul>
    </div>
  </body>
</html>"""
GENERATED = (TARGET.replace("condizioni?utm_source=x", "condizioni-2026")
             .replace("Gentile cliente,", "Gentile signora,"))
LINK_LINE = next(i for i, line in enumerate(TARGET.splitlines()) if "<a href" in line)


def link_diff():
    return fake_diff("cambiato", "link", "https://example.invalid/condizioni",
                     "https://example.invalid/condizioni-2026",
                     detail="href: https://example.invalid/condizioni → https://example.invalid/condizioni-2026")


# ------------------------------------------------------------------ the map ---

def test_the_tree_holds_the_blocks_below_body_with_their_steps_and_text():
    src = parse(TARGET)
    body = next(n for n in src.nodes if n.tag == "body")
    assert [n.step for n in body.children] == ["table[1]", "p[1]", "div[1]"]
    p = body.children[1]
    assert p.preview() == "Per i dettagli Scopri le condizioni del servizio."
    assert "a" not in {n.tag for n in src.nodes}, "inline elements are not blocks"
    assert not any(n.tag in ("title", "style") for n in src.nodes)
    li = [n for n in src.nodes if n.tag == "li"]
    assert [n.path for n in li] == ["html[1]/body[1]/div[1]/ul[1]/li[1]", "html[1]/body[1]/div[1]/ul[1]/li[2]"]
    assert node_at(src, LINK_LINE) is p


def test_a_link_diff_is_on_its_attribute_line_even_normalised():
    d = link_diff()
    lines = locate([d], parse(TARGET), parse(GENERATED))
    assert lines[d.id] == (LINK_LINE, LINK_LINE)


def test_text_split_by_an_inline_tag_and_repeats_are_found_in_order():
    a = fake_diff("cambiato", "testo", "le condizioni del", "le condizioni del")
    b = fake_diff("cambiato", "testo", "Gentile cliente,", "Gentile signora,")
    c = fake_diff("in_piu", "testo", "", "Tre", before="Uno Due")
    left, right = parse(TARGET), parse(GENERATED)
    lines = locate([b, a, c], left, right)
    target = TARGET.splitlines()
    assert "Gentile cliente," in target[lines[b.id][0]]
    assert "Gentile signora," in GENERATED.splitlines()[lines[b.id][1]]
    assert "Scopri le" in target[lines[a.id][0]], "the phrase starts before the <b>"
    assert "Due" in target[lines[c.id][0]], "an insertion sits after its context"
    assert lines[c.id][1] is not None


def test_what_is_not_there_is_none():
    d = fake_diff("cambiato", "testo", "assente del tutto", "neppure qui")
    assert locate([d], parse(TARGET), parse(GENERATED))[d.id] == (None, None)
    assert parse("").nodes == []


# ----------------------------------------------------------- the case view ---

def _html_case(qtbot, page, fake_core, tmp_path, diffs):
    case = open_case(page, fake_core, tmp_path, target=False)
    api = fake_core.officina
    source = tmp_path / "cliente" / "Email del cliente.html"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text("<html><body><p>Gentile cliente,</p></body></html>", encoding="utf-8")
    api.set_target(case, source)
    filler = "<p>Testo di esempio del messaggio generato.</p>" * 20
    api.set_response(f"<html><body><p>Gentile signora,</p>{filler}</body></html>".encode())
    api.generate(page.ini, case, "tobe")
    api.set_canned(case.id, 1, diffs)
    api.set_dom_view(case.id, (TARGET, GENERATED))
    page.refresh()
    page.open_case(case.id)
    view = page.case_view
    qtbot.waitUntil(lambda: view.docs is not None and view.docs.judged is not None, timeout=15000)
    return view


def test_the_dom_switch_is_hidden_for_a_pdf_case(qtbot, page, fake_core, tmp_path):
    case = open_case(page, fake_core, tmp_path)
    fake_core.officina.generate(page.ini, case, "tobe")
    page.refresh()
    page.open_case(case.id)
    view = page.case_view
    qtbot.waitUntil(lambda: view.docs is not None and view.docs.right.version is not None, timeout=15000)
    assert not view.view_switch.isVisibleTo(view)
    view.set_dom_mode(True)
    assert not view.dom_mode(), "no DOM tab for a PDF"
    assert view.left.isVisibleTo(view) and view.right.isVisibleTo(view)


def test_an_html_case_shows_the_dom_and_shares_the_selection(qtbot, page, fake_core, tmp_path):
    text = fake_diff("cambiato", "testo", "Gentile cliente,", "Gentile signora,")
    view = _html_case(qtbot, page, fake_core, tmp_path, [text, link_diff()])
    assert view.view_switch.isVisibleTo(view)
    view.dom_button.click()
    assert view.dom_mode() and not view.left.isVisibleTo(view)
    dom = view.dom
    qtbot.waitUntil(lambda: dom.stack.currentWidget() is dom.splitter, timeout=10000)
    judged = view.docs.judged.judged
    link = next(j.diff.id for j in judged if j.diff.klass == "link")
    other = next(j.diff.id for j in judged if j.diff.klass == "testo")

    # the list -> the DOM
    row = view.diffs.row_ids().index(link)
    view.diffs.list.setCurrentRow(row)
    assert dom.current_line("left") == LINK_LINE and dom.current_line("right") == LINK_LINE
    item = dom.tree.currentItem()
    assert item is not None and "p[1]" in item.text(0)
    assert dom.left.extraSelections(), "the lines are tinted"

    # the DOM -> the list
    line = dom.line_of(other)[1]
    cursor = QTextCursor(dom.right.document().findBlockByNumber(line))
    dom.right.setTextCursor(cursor)
    assert view.diffs.current_id() == other
    assert dom.current_line("left") == dom.line_of(other)[0]

    # the tree -> the list
    dom.tree.itemClicked.emit(dom.item_of_line(LINK_LINE), 0)
    assert view.diffs.current_id() == link

    view.docs_button.click()
    assert not view.dom_mode() and view.left.isVisibleTo(view)


def test_the_tree_marks_a_block_with_its_verdict_glyph(qtbot, page, fake_core, tmp_path):
    from qtrequestory.ui.pages.officina_verdict_style import look_for

    view = _html_case(qtbot, page, fake_core, tmp_path, [link_diff()])
    view.set_dom_mode(True)
    qtbot.waitUntil(lambda: view.dom.stack.currentWidget() is view.dom.splitter, timeout=10000)
    j = view.docs.judged.judged[0]
    item = view.dom.item_of_line(LINK_LINE)
    assert item.text(0).startswith(look_for(j).icon + " ")
    untouched = view.dom.item_of_line(next(i for i, line in enumerate(TARGET.splitlines()) if "Uno" in line))
    assert not untouched.text(0).startswith(look_for(j).icon)


def test_a_failed_source_is_a_sentence(qtbot, page, fake_core, tmp_path, monkeypatch):
    view = _html_case(qtbot, page, fake_core, tmp_path, [link_diff()])

    def boom(*_a):
        raise ValueError("sorgente illeggibile")

    monkeypatch.setattr(fake_core.officina, "dom_view", boom)
    view.set_dom_mode(True)
    expected = strings.DOM_FAILED.format(reason="sorgente illeggibile")
    qtbot.waitUntil(lambda: view.dom.message.text() == expected, timeout=10000)


def test_reopening_the_case_keeps_the_dom_on_the_lists_selection(qtbot, page, fake_core, tmp_path):
    text = fake_diff("cambiato", "testo", "Gentile cliente,", "Gentile signora,")
    view = _html_case(qtbot, page, fake_core, tmp_path, [link_diff(), text])
    view.set_dom_mode(True)
    qtbot.waitUntil(lambda: view.dom.stack.currentWidget() is view.dom.splitter, timeout=10000)
    link = next(j.diff.id for j in view.docs.judged.judged if j.diff.klass == "link")
    view.diffs.list.setCurrentRow(view.diffs.row_ids().index(link))
    old = view.docs
    page.open_initiative(page.ini.id)
    page.open_case(view.case.id)
    qtbot.waitUntil(lambda: view.docs is not old and view.docs is not None and view.docs.judged is not None,
                    timeout=10000)
    assert view.dom.current_line("left") == view.dom.line_of(view.diffs.current_id())[0]


def test_an_alt_also_in_the_title_lands_on_its_img_line_not_in_head():
    pretty = TARGET.replace("<title>\n      Oggetto", "<title>\n      Logo")
    img = next(i for i, line in enumerate(pretty.splitlines()) if "<img" in line)
    d = fake_diff("cambiato", "link", "Logo", "Marchio", detail="alt: Logo → Marchio")
    left = parse(pretty)
    assert left.hidden and all(i not in left.hidden for i in range(img - 1, img + 2))
    assert locate([d], left, parse(pretty))[d.id][0] == img


def test_the_attribute_name_picks_the_right_line():
    pretty = TARGET.replace('alt="Logo"', 'alt="https://example.invalid/logo.png"')
    img = next(i for i, line in enumerate(pretty.splitlines()) if "<img" in line)
    d = fake_diff("cambiato", "link", "https://example.invalid/logo.png", "https://example.invalid/b.png",
                  detail="src: https://example.invalid/logo.png → https://example.invalid/b.png")
    assert locate([d], parse(pretty), parse(pretty))[d.id][0] == img


def test_the_longest_word_places_a_diff_only_when_it_is_unique():
    unique = fake_diff("cambiato", "testo", "Assistenza dettagliata", "x")   # "dettagliata": not there
    once = fake_diff("cambiato", "testo", "servizio. rapido", "x")          # "servizio.": once
    left = parse(TARGET)
    lines = locate([unique, once], left, left)
    assert lines[unique.id][0] is None, "no common-word guess: only in the list"
    assert "del servizio." in TARGET.splitlines()[lines[once.id][0]]


def test_a_redraw_keeps_the_collapsed_branches(qtbot):
    from qtrequestory.ui.contracts import Judged
    from qtrequestory.ui.pages.officina_dom import DomTab

    tab = DomTab()
    qtbot.addWidget(tab)
    tab.show_sources("k", TARGET, GENERATED)
    table = tab.item_of_line(next(i for i, line in enumerate(TARGET.splitlines()) if "<table>" in line))
    table.setExpanded(False)
    tab.set_judged([Judged(link_diff(), "da_fare")])
    assert not table.isExpanded(), "the same item, still collapsed"
    assert tab.item_of_line(LINK_LINE).text(0).startswith("○")
    tab.set_judged([Judged(link_diff(), "da_fare"), Judged(fake_diff("cambiato", "testo", "Uno", "Tre"), None)])
    assert tab.tree.topLevelItemCount() == 3


def test_an_unknown_state_sorts_last():
    from qtrequestory.ui.pages.officina_dom import _rank

    assert _rank("regressione") < _rank("da_fare") < _rank("tollerata") < _rank("fatta") < _rank("nuovo")


def test_a_new_target_refreshes_the_dom_tab(qtbot, page, fake_core, tmp_path, monkeypatch):
    view = _html_case(qtbot, page, fake_core, tmp_path, [link_diff()])
    api = fake_core.officina
    calls = []
    real = api.dom_view
    monkeypatch.setattr(api, "dom_view", lambda case, version: calls.append(1) or real(case, version))
    view.set_dom_mode(True)
    qtbot.waitUntil(lambda: len(calls) == 1 and view.dom.stack.currentWidget() is view.dom.splitter,
                    timeout=10000)
    view.set_dom_mode(False)
    source = tmp_path / "cliente" / "Email del cliente.html"   # same name: same path in the case
    source.write_text("<html><body><p>Gentile cliente, nuova versione del target.</p></body></html>",
                      encoding="utf-8")
    api.set_dom_view(view.case.id, (TARGET.replace("Testo libero", "Testo nuovo"), GENERATED))
    case = view.case
    old = view.docs
    api.set_target(case, source)
    page.refresh()
    page.open_case(case.id)
    qtbot.waitUntil(lambda: view.docs is not old and view.docs is not None and view.docs.judged is not None,
                    timeout=15000)
    view.set_dom_mode(True)
    qtbot.waitUntil(lambda: len(calls) == 2, timeout=10000)
    qtbot.waitUntil(lambda: "Testo nuovo" in view.dom.left.toPlainText(), timeout=10000)
