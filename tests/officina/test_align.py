"""Block alignment, target side first (spec §4.2 step 7, §11)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from qtrequestory.officina.compare.align import THRESHOLD, align
from qtrequestory.officina.compare.blocks import make_blocks
from qtrequestory.officina.compare.model import Block, Word

ROOT = Path(__file__).resolve().parents[2]


def _block(i: int, text: str, *, page: int = 0, kind: str = "paragrafo", html: bool = False) -> Block:
    words, x = [], 42.0
    for token in text.split():
        if html:
            words.append(Word(token, 0, 0.0, 0.0, 0.0, 0.0))
        else:
            words.append(Word(token, page, x, 60.0, x + 5.5 * len(token), 71.0, 11.0))
            x += 5.5 * (len(token) + 1)
    return Block(i, tuple(words), 0 if html else page, "html" if html else kind)  # type: ignore[arg-type]


def _blocks(texts: list[str], **kw) -> list[Block]:
    return [_block(i, t, **kw) for i, t in enumerate(texts)]


A = "Il presente contratto regola la fornitura del servizio tra le parti indicate"
B = "Il cliente dichiara di aver ricevuto copia delle condizioni generali prima della firma"
C = "Il corrispettivo è indicato nella scheda allegata e resta invariato per dodici mesi"
D = "Per ogni comunicazione il cliente può scrivere all'indirizzo indicato nel sito"
LEGAL = ("Informativa sul trattamento dei dati personali ai sensi del regolamento europeo il titolare "
         "tratta i dati per le finalità indicate")


def test_threshold_value():
    assert THRESHOLD == 0.35


def test_identical_documents_pair_in_order():
    blocks = _blocks([A, B, C, D])
    assert align(blocks, _blocks([A, B, C, D])) == [(0, 0), (1, 1), (2, 2), (3, 3)]


def test_empty_sides():
    assert align([], []) == []
    assert align(_blocks([A]), []) == [(0, None)]
    assert align([], _blocks([A, B])) == [(None, 0), (None, 1)]


def test_missing_paragraph_is_left_alone():
    assert align(_blocks([A, B, C, D]), _blocks([A, C, D])) == [(0, 0), (1, None), (2, 1), (3, 2)]


def test_extra_blocks_go_where_their_neighbours_put_them():
    assert align(_blocks([A, C]), _blocks([A, B, C])) == [(0, 0), (None, 1), (1, 2)]
    assert align(_blocks([B]), _blocks([D, B])) == [(None, 0), (0, 1)]
    assert align(_blocks([A, B]), _blocks([A, B, C, D])) == [(0, 0), (1, 1), (None, 2), (None, 3)]


def test_unrelated_blocks_stay_unpaired():
    assert align(_blocks([A]), _blocks(["zzz yyy xxx www vvv uuu ttt sss rrr"])) == [(0, None), (None, 0)]


def test_a_changed_word_still_pairs():
    changed = C.replace("dodici", "ventiquattro")
    assert align(_blocks([A, B, C]), _blocks([A, B, changed])) == [(0, 0), (1, 1), (2, 2)]


def test_short_blocks_use_the_word_ratio():
    left = _blocks(["Art. 1 Oggetto", "Art. 2 Durata", A])
    right = _blocks(["Art. 1 Oggetto del contratto", "Art. 2 Durata", A])
    assert align(left, right) == [(0, 0), (1, 1), (2, 2)]


def test_moved_block_pairs_across_the_document():
    left = _blocks([LEGAL, A, B, C])
    assert align(left, _blocks([A, B, C, LEGAL])) == [(0, 3), (1, 0), (2, 1), (3, 2)]
    reworded = LEGAL.replace("europeo", "comunitario")  # not an exact match: the Hungarian pairs it
    assert align(left, _blocks([A, B, C, reworded])) == [(0, 3), (1, 0), (2, 1), (3, 2)]


ROW = "Nome .......... Cognome .........."


@pytest.mark.parametrize("variant", ["identical", "filled", "filled_same", "shifted", "one_less"])
def test_repeated_form_rows_align_in_order(variant: str):
    """Review Focus 1: ten identical label rows must pair i↔i, never cross."""
    target = _blocks([A] + [ROW] * 10 + [D], kind="riga_modulo")
    rows: list[str] = {
        "identical": [ROW] * 10,
        "filled": [f"Nome Anna{k} Cognome Neri{k}" for k in range(10)],
        "filled_same": ["Nome Mario Cognome Rossi"] * 10,
        "shifted": [f"Nome Anna{k} Cognome Neri{k}" for k in range(10)],
        "one_less": [ROW] * 9,
    }[variant]
    before = [A, B, C] if variant == "shifted" else [A]
    generated = _blocks(before + rows + [D])
    pairs = align(target, generated)
    offset = len(before) - 1
    row_pairs = [(i, j) for i, j in pairs if i is not None and 1 <= i <= 10]
    matched = [(i, j) for i, j in row_pairs if j is not None]
    assert [j for _, j in matched] == [k + offset for k in range(1, len(rows) + 1)]  # every row, in order
    if len(rows) == 10:
        assert matched == [(i, i + offset) for i in range(1, 11)]
    else:  # one row fewer: which one stays unpaired is free (they are equal); never crossed
        assert [i for i, _ in matched] == sorted(i for i, _ in matched)
    assert (0, 0) in pairs and (11, len(generated) - 1) in pairs


def test_repeated_form_rows_in_pdfs(pdfs: Path):
    from qtrequestory.officina.compare.extract_pdf import extract
    from tests.officina import pdfgen

    intro, outro = pdfgen.lorem(40, seed=1), pdfgen.lorem(30, seed=2)
    target = make_blocks(extract(pdfgen.paragraphs_pdf(pdfs / "t.pdf", [intro] + [ROW] * 10 + [outro])).words)
    rows = [f"Nome Anna{k} Cognome Neri{k}" for k in range(10)]
    generated = make_blocks(extract(pdfgen.paragraphs_pdf(pdfs / "g.pdf", [intro, pdfgen.lorem(20, seed=9)]
                                                           + rows + [outro])).words)
    assert len(target) == 12 and len(generated) == 13
    assert align(target, generated) == [(0, 0), (None, 1)] + [(i, i + 1) for i in range(1, 12)]


def test_legal_block_top_and_bottom_in_pdfs(pdfs: Path):
    from qtrequestory.officina.compare.extract_pdf import extract
    from tests.officina import pdfgen

    body = [pdfgen.lorem(45, seed=s) for s in (11, 12, 13)]
    top = make_blocks(extract(pdfgen.paragraphs_pdf(pdfs / "top.pdf", [LEGAL] + body)).words)
    bottom = make_blocks(extract(pdfgen.paragraphs_pdf(pdfs / "bottom.pdf", body + [LEGAL])).words)
    assert align(top, bottom) == [(0, 3), (1, 0), (2, 1), (3, 2)]


def test_missing_paragraph_in_pdfs(pdfs: Path):
    from qtrequestory.officina.compare.extract_pdf import extract
    from tests.officina import pdfgen

    paragraphs = [pdfgen.lorem(35, seed=s) for s in (21, 22, 23, 24)]
    left = make_blocks(extract(pdfgen.paragraphs_pdf(pdfs / "l.pdf", paragraphs)).words)
    right = make_blocks(extract(pdfgen.paragraphs_pdf(pdfs / "r.pdf", paragraphs[:2] + paragraphs[3:])).words)
    assert align(left, right) == [(0, 0), (1, 1), (2, None), (3, 2)]


def test_html_blocks_align_by_order_only():
    left = _blocks([A, B, C, D, LEGAL], html=True)
    right = _blocks([A, C.replace("dodici", "sei"), D, B, LEGAL, "Link di disiscrizione alla newsletter"], html=True)
    assert align(left, right) == [(0, 0), (1, 3), (2, 1), (3, 2), (4, 4), (None, 5)]


def _long(n: int, *, changed: bool) -> list[Block]:
    """``n`` similar blocks on n/10 pages: the same clause with a block number."""
    base = "clausola di prova numero {k} con testo simile in ogni blocco del documento sintetico {k}"
    out = []
    for k in range(n):
        text = base.format(k=k) + (" modificata" if changed else "")
        out.append(_block(k, text, page=k // 10))
    return out


def test_long_similar_documents_are_windowed_and_fast(monkeypatch):
    from qtrequestory.officina.compare import align as module

    sizes: list[tuple[int, int]] = []
    real = module.solve

    def spy(cost):
        sizes.append((len(cost), len(cost[0]) if cost else 0))
        return real(cost)

    monkeypatch.setattr(module, "solve", spy)
    left, right = _long(420, changed=False), _long(420, changed=True)
    start = time.perf_counter()
    pairs = align(left, right)
    elapsed = time.perf_counter() - start
    assert pairs == [(k, k) for k in range(420)]
    assert len(sizes) >= 2 and max(r for r, _ in sizes) <= 300  # one group of 420, cut into windows
    assert elapsed < 10, elapsed


def _spy_solve(monkeypatch) -> list[tuple[int, int]]:
    from qtrequestory.officina.compare import align as module

    sizes: list[tuple[int, int]] = []
    real = module.solve

    def spy(cost):
        sizes.append((len(cost), len(cost[0]) if cost else 0))
        return real(cost)

    monkeypatch.setattr(module, "solve", spy)
    return sizes


def test_windows_keep_partners_when_the_generated_side_gains_a_page(monkeypatch):
    sizes = _spy_solve(monkeypatch)
    left = _long(420, changed=False)
    extra = [_block(k, f"pagina aggiunta {k} " + _filler(k), page=0) for k in range(10)]
    shifted = [_block(10 + k, b_text, page=(10 + k) // 10)
               for k, b_text in enumerate(" ".join(w.text for w in b.words) for b in _long(420, changed=True))]
    pairs = align(left, extra + shifted)
    assert [p for p in pairs if p[0] is not None] == [(k, k + 10) for k in range(420)]
    assert len(sizes) >= 2 and max(r for r, _ in sizes) <= 300


def _filler(seed: int) -> str:
    from tests.officina import pdfgen

    return pdfgen.lorem(12, seed=100 + seed)


def test_html_is_detected_by_kind_not_by_page(monkeypatch):
    sizes = _spy_solve(monkeypatch)
    one_page = [Block(b.id, b.words, 0, "paragrafo") for b in _long(420, changed=False)]
    one_page_r = [Block(b.id, b.words, 0, "paragrafo") for b in _long(420, changed=True)]
    assert align(one_page, one_page_r) == [(k, k) for k in range(420)]
    assert [r for r, _ in sizes] == [420]  # a one-page PDF: a single window
    sizes.clear()
    html_l = [Block(b.id, tuple(Word(w.text, 0, 0, 0, 0, 0) for w in b.words), 0, "html")
              for b in _long(420, changed=False)]
    html_r = [Block(b.id, tuple(Word(w.text, 0, 0, 0, 0, 0) for w in b.words), 0, "html")
              for b in _long(420, changed=True)]
    assert align(html_l, html_r) == [(k, k) for k in range(420)]
    assert len(sizes) >= 2 and max(r for r, _ in sizes) <= 300


def test_repeated_rows_after_a_large_insertion_keep_their_partners():
    """Review probe: 100 identical rows after 60 inserted paragraphs; every
    posting of the rows' keys is longer than POSTING_CAP."""
    from tests.officina import pdfgen

    target = _blocks([A] + [ROW] * 100 + [D], kind="riga_modulo")
    inserted = [pdfgen.lorem(30, seed=500 + k) for k in range(60)]
    generated = _blocks([A] + inserted + [f"Nome Anna{k} Cognome Neri{k}" for k in range(100)] + [D])
    pairs = dict(p for p in align(target, generated) if p[0] is not None)
    assert [pairs[i] for i in range(1, 101)] == [i + 60 for i in range(1, 101)]


_SCRIPT = """
import json, sys
sys.path.insert(0, {src!r}); sys.path.insert(0, {root!r})
from tests.officina.test_align import _blocks, A, B, C, D, LEGAL, ROW
from qtrequestory.officina.compare.align import align
left = _blocks([A, ROW, ROW, ROW, B, C, LEGAL, D], kind="riga_modulo")
right = _blocks([LEGAL, A, "Nome x Cognome y", ROW, "Nome z Cognome w", ROW, C, B, D, "extra blocco"])
print(json.dumps(align(left, right)))
"""


def test_deterministic_across_runs_and_hash_seeds():
    script = _SCRIPT.format(src=str(ROOT / "src"), root=str(ROOT))
    outputs = []
    for seed in ("1", "2", "12345"):
        env = {**os.environ, "PYTHONHASHSEED": seed}
        done = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True,
                              check=True, cwd=ROOT)
        outputs.append(json.loads(done.stdout))
    assert outputs[0] == outputs[1] == outputs[2]
    left = _blocks([A, ROW, ROW, ROW, B, C, LEGAL, D], kind="riga_modulo")
    right = _blocks([LEGAL, A, "Nome x Cognome y", ROW, "Nome z Cognome w", ROW, C, B, D, "extra blocco"])
    assert [list(p) for p in align(left, right)] == outputs[0]
    assert align(left, right) == align(left, right)


def test_many_short_rows_sharing_words_stay_fast_and_in_order():
    """Every row shares "Voce"/"valore": candidates come from the nearest
    postings only (POSTING_CAP), not from every pair."""
    left = [_block(k, f"Voce {k % 7} valore {k}", page=k // 40) for k in range(600)]
    right = [_block(k, f"Voce {k % 7} valore {k}x", page=k // 40) for k in range(600)]
    start = time.perf_counter()
    pairs = align(left, right)
    assert pairs == [(k, k) for k in range(600)]
    assert time.perf_counter() - start < 10


@pytest.mark.parametrize("last_changed", [False, True])
def test_repeated_rows_at_the_end_after_a_large_insertion_keep_their_partners(last_changed: bool):
    """Re-review probe: no exact match follows the rows (a closing section of
    form rows ends the document), so the end of the document is the anchor."""
    from tests.officina import pdfgen

    target = _blocks([A] + [ROW] * 100, kind="riga_modulo")
    inserted = [pdfgen.lorem(30, seed=700 + k) for k in range(60)]
    rows = [f"Nome Anna{k} Cognome Neri{k}" for k in range(100)]
    if last_changed:
        target = _blocks([A] + [ROW] * 100 + [D], kind="riga_modulo")
        rows.append(D.replace("sito", "portale"))
    generated = _blocks([A] + inserted + rows)
    pairs = dict(p for p in align(target, generated) if p[0] is not None)
    assert [pairs[i] for i in range(1, 101)] == [i + 60 for i in range(1, 101)]
