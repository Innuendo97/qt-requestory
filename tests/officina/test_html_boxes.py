"""qtrequestory.officina.compare.html_boxes: HTML words boxed from the Edge
print (spec §6). Synthetic words, no PDF, no Edge."""
from __future__ import annotations

from qtrequestory.officina.compare.extract_html import extract_html
from qtrequestory.officina.compare.extract_pdf import DocText
from qtrequestory.officina.compare.html_boxes import place
from qtrequestory.officina.compare.model import Word

HTML = b"<body><p>Gentile cliente,</p><p>il prezzo resta fisso per dodici mesi.</p></body>"


def _print(*lines: str, page: int = 0) -> DocText:
    words = []
    for row, line in enumerate(lines):
        x = 40.0
        for token in line.split():
            words.append(Word(token, page, x, 50.0 + 14 * row, x + 5.0 * len(token), 61.0 + 14 * row, 11.0, True))
            x += 5.0 * (len(token) + 1)
    return DocText(words, [(595.0, 842.0)], True)


def test_words_take_the_boxes_of_the_same_words_in_the_print():
    blocks, _ = extract_html(HTML)
    printed = _print("Gentile cliente,", "il prezzo resta fisso per dodici mesi.")
    placed = place(blocks, printed)
    assert [w.text for b in placed for w in b.words] == [w.text for w in printed.words]
    for got, want in zip((w for b in placed for w in b.words), printed.words, strict=True):
        assert (got.page, got.x0, got.y0, got.x1, got.y1) == (want.page, want.x0, want.y0, want.x1, want.y1)
        assert (got.size, got.bold) == (0.0, False), "no font from the print"


def test_a_word_the_print_cut_differently_goes_next_to_its_neighbour():
    blocks, _ = extract_html(b"<body><p>scrivi alla e-mail indicata</p></body>")
    printed = _print("scrivi alla e- mail indicata")
    words = place(blocks, printed)[0].words
    alla, email, indicata = words[1], words[2], words[3]
    assert email.text == "e-mail" and email.page == 0
    assert email.x0 > alla.x1 and email.y0 == alla.y0 and email.x1 > email.x0
    assert indicata.x0 == printed.words[4].x0


def test_a_block_missing_from_the_print_order_is_searched():
    blocks, _ = extract_html(b"<body><p>colonna destra</p><p>colonna sinistra</p></body>")
    printed = _print("testo tutto diverso")
    asked: list[str] = []

    def search(text: str):
        asked.append(text)
        return [(1, (100.0, 200.0, 300.0, 212.0))] if text == "colonna destra" else []

    placed = place(blocks, printed, search)
    assert "colonna destra" in asked
    first = placed[0]
    assert first.page == 1 and all(w.page == 1 and w.y0 == 200.0 for w in first.words)
    assert first.words[0].x0 == 100.0 and first.words[-1].x1 == 300.0
    assert all(w.x1 == 0.0 for w in placed[1].words), "not found anywhere: zero boxes stay"


def test_no_print_leaves_the_blocks_as_they_are():
    blocks, _ = extract_html(HTML)
    assert place(blocks, None) == blocks
    assert place(blocks, DocText([], [(595.0, 842.0)], False)) == blocks


def test_a_huge_document_skips_the_matcher_and_searches_its_blocks(monkeypatch):
    import time

    from qtrequestory.officina.compare import html_boxes

    monkeypatch.setattr(html_boxes, "PLACE_MAX", 1000)
    html = "<body>" + "".join(f"<p>riga {n} uguale uguale uguale</p>" for n in range(600)) + "</body>"
    blocks, _ = extract_html(html.encode())
    printed = _print(*(f"riga {n} uguale uguale uguale" for n in range(600)))
    asked: list[str] = []

    def search(text: str):
        asked.append(text)
        return [(0, (10.0, 20.0, 110.0, 32.0))]

    started = time.monotonic()
    placed = place(blocks, printed, search)
    assert time.monotonic() - started < 5
    assert len(asked) == 600, "every block searched: the matcher was skipped"
    assert all(w.x0 >= 10.0 and w.y0 == 20.0 for b in placed for w in b.words)
    assert place(blocks, printed) == blocks, "no search: the zero boxes stay"
