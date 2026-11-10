"""qtrequestory.officina.batch.runner: a whole Genera run.

The calls come from a REAL index over synthetic daily files and go to the
loopback ``FakeServer`` (never a real endpoint). Concurrency is driven with
barriers and events, never with sleeps. Synthetic data only (public repo).
"""
from __future__ import annotations

import csv
import dataclasses
import itertools
import json
import logging
import sqlite3
import threading
from collections.abc import Callable
from datetime import date, datetime
from pathlib import Path

import pytest

from qtrequestory.core.config import GeneratorEndpoint, OfficinaSettings
from qtrequestory.core.events import CancelToken, null_sink
from qtrequestory.core.index.builder import IndexBuilder
from qtrequestory.core.index.db import open_index
from qtrequestory.core.index.search import SearchHit, SearchQuery, read_body, search
from qtrequestory.officina.batch import output
from qtrequestory.officina.batch.elenco import NO_PACKAGE, Elenco, ElencoRow
from qtrequestory.officina.batch.headers import default_rows
from qtrequestory.officina.batch.memory import HtmlMemory
from qtrequestory.officina.batch.model import BatchItemDone, BatchRequest, BatchStarted, Target
from qtrequestory.officina.batch.resolve import targets_from_fdis, targets_from_keys
from qtrequestory.officina.batch.runner import WORKERS, count_calls, reason_generator_gone, run_batch
from qtrequestory.officina.generator import REASON_NOT_A_DOCUMENT
from tests.conftest import FDI_A, FDI_B, entry_name, make_daily_file, synthetic_body
from tests.officina._server import HTML, PDF, Canned, FakeServer
from tests.officina.test_links import SIG, sas

KEY_A, KEY_B, KEY_C, KEY_D = "MOD_TEST_A", "MOD_TEST_B", "MOD_TEST_C", "MOD_TEST_D"
KEY_BAD = "MOD_TEST_BAD"      # its logged body is not JSON
KEY_SECRET = "MOD_TEST_SECRET"  # its payload carries markers that must never leak
KEYS_F = [f"MOD_TEST_F{i}" for i in range(6)]
NOW = datetime(2026, 11, 10, 14, 30, 5)
RUN = "svil_20261110-143005"
SECRET = "SEGRETO_CLIENTE_ROSSI"


class RealIndex:
    """The two methods of ``IndexService`` that Genera uses, over a real DB."""

    def __init__(self, conn, root: Path) -> None:
        self.conn, self.root = conn, root

    def search(self, query: SearchQuery) -> list[SearchHit]:
        return search(self.conn, self.root, query)

    def read_body(self, hit: SearchHit) -> bytes:
        return read_body(hit)


@pytest.fixture
def index(tmp_path: Path):
    root = tmp_path / "mirror"
    secret_body = json.dumps({"documents": [{"template": {"templateKey": KEY_SECRET}}],
                              "customers": [{"name": SECRET}],
                              "attachmentUrl": sas()}).encode()
    entries = [(entry_name(FDI_A, k, f"0a0a0a0a0000000{i}"), synthetic_body(FDI_A, k))
               for i, k in enumerate((KEY_A, KEY_B, KEY_C))]
    entries += [(entry_name(FDI_B, KEY_D, "0b0b0b0b00000001"), synthetic_body(FDI_B, KEY_D)),
                (entry_name(FDI_B, KEY_BAD, "0b0b0b0b00000002"), b"questo non e' un JSON"),
                (entry_name(FDI_B, KEY_SECRET, "0b0b0b0b00000003"), secret_body)]
    entries += [(entry_name(FDI_B, k, f"0c0c0c0c0000000{i}"), synthetic_body(FDI_B, k))
                for i, k in enumerate(KEYS_F)]
    make_daily_file(root, "coll", date(2026, 11, 9), entries)
    conn = open_index(":memory:")
    IndexBuilder(conn, root, null_sink).update(["coll"])
    yield RealIndex(conn, root)
    conn.close()


@pytest.fixture
def server():
    s = FakeServer()
    yield s
    s.close()


def by_key(**answers: Canned):
    """A ``server.route`` answering per ``template_key`` header (PDF otherwise)."""
    def route(headers: dict[str, str], body: bytes) -> Canned:
        key = next((v for k, v in headers.items() if k.casefold() == "template_key"), "")
        return answers.get(key, Canned())
    return route


class Env:
    def __init__(self, tmp_path: Path, index: RealIndex, server: FakeServer) -> None:
        self.tmp_path, self.index, self.server = tmp_path, index, server
        self.settings = OfficinaSettings(generators=[GeneratorEndpoint("svil", server.url)],
                                         header_profile={"office_id": "00001"}, timeout_s=10)
        self.memory = HtmlMemory(tmp_path / "genera-html.json")
        self.destination = tmp_path / "out"
        self.events: list = []
        self.uuids = (f"uuid-{n}" for n in range(1, 10_000))

    @property
    def run_dir(self) -> Path:
        return self.destination / RUN

    def request(self, targets, **kw) -> BatchRequest:
        values = dict(generator="svil", source_env="coll", targets=tuple(targets),
                      header_rows=tuple(default_rows(self.settings)), destination=self.destination,
                      save_html=False, make_zip=False)
        values.update(kw)
        return BatchRequest(**values)

    def run(self, targets, *, cancel=None, sink=None, index=None, **kw):
        # a settings SOURCE: a test that replaces self.settings mid-run is seen by the rows
        return run_batch(self.request(targets, **kw), index=index or self.index,
                         settings=lambda: self.settings, memory=self.memory, clock=lambda: NOW,
                         new_uuid=lambda: next(self.uuids), sink=sink or self.events.append,
                         cancel=cancel)

    def count(self, targets, *, cancel=None, **kw) -> int:
        return count_calls(self.request(targets, **kw), index=self.index, settings=self.settings,
                           memory=self.memory, cancel=cancel)


@pytest.fixture
def env(tmp_path: Path, index: RealIndex, server: FakeServer) -> Env:
    return Env(tmp_path, index, server)


def keys(*names: str, folders=(NO_PACKAGE,)) -> tuple[Target, ...]:
    return tuple(Target("key", n, folders) for n in names)


def esito_rows(run_dir: Path) -> list[list[str]]:
    text = (run_dir / "esito.csv").read_text(encoding="utf-8-sig")
    return list(csv.reader(text.splitlines(), delimiter=";"))[1:]


def parts(root: Path) -> list[Path]:
    return [p for p in root.rglob("*") if p.name.endswith(".part")]


# ------------------------------------------------------------------ writing ---

def test_pdf_saved_under_package_folder(env: Env):
    elenco = Elenco(rows=(ElencoRow(KEY_A, "111_PKG"),), skipped=0)
    report = env.run(targets_from_keys([KEY_A.lower()], elenco))
    (o,) = report.outcomes
    pdf = env.run_dir / "111_PKG" / f"{KEY_A}.pdf"
    assert (o.status, o.key, o.doc_type, o.http_status, o.files) == ("ok", KEY_A, "pdf", 200, (pdf,))
    assert pdf.read_bytes() == PDF and report.run_dir == env.run_dir and not report.cancelled
    assert esito_rows(env.run_dir)[0][:4] == [KEY_A, "111_PKG", FDI_A, "ok"]


def test_key_in_two_packages_called_once_written_twice(env: Env):
    elenco = Elenco(rows=(ElencoRow(KEY_A, "111_PKG"), ElencoRow(KEY_A, "222_PKG")), skipped=0)
    (o,) = env.run(targets_from_keys([KEY_A], elenco)).outcomes
    assert len(env.server.requests) == 1
    assert o.files == (env.run_dir / "111_PKG" / f"{KEY_A}.pdf", env.run_dir / "222_PKG" / f"{KEY_A}.pdf")
    assert all(f.read_bytes() == PDF for f in o.files)


def test_fdi_target_writes_under_fdi_folder(env: Env):
    report = env.run(targets_from_fdis([FDI_A]))
    assert {o.key for o in report.outcomes} == {KEY_A, KEY_B, KEY_C}
    assert all(o.status == "ok" and o.fdi == FDI_A and o.folders == (FDI_A,) for o in report.outcomes)
    assert sorted(p.name for p in (env.run_dir / FDI_A).iterdir()) == [f"{k}.pdf" for k in (KEY_A, KEY_B, KEY_C)]
    correlation = [_header(h, "correlation_id") for h, _ in env.server.requests]
    assert len(set(correlation)) == 3  # a new correlation_id per call, even within an FDI


class _Renaming(RealIndex):
    """The real index, with some template keys spelled otherwise in its hits."""

    def __init__(self, env: Env, spelled: dict[str, str]) -> None:
        super().__init__(env.index.conn, env.index.root)
        self.spelled = spelled

    def search(self, query):
        return [dataclasses.replace(h, template_key=self.spelled.get(h.template_key, h.template_key))
                for h in super().search(query)]


def _held(env: Env, hold) -> Callable[[object], None]:
    """Route the server so the request ``hold(headers, n)`` picks (``n``: its
    arrival number) answers only once another row is done; returns the sink
    that releases it. Every answer is a PDF ending with its template key."""
    other_done = threading.Event()
    arrivals = itertools.count()

    def sink(event) -> None:
        env.events.append(event)
        if isinstance(event, BatchItemDone):
            other_done.set()

    def route(headers, _body):
        key = _header(headers, "template_key")
        if hold(key, next(arrivals)):
            assert other_done.wait(10)
        return Canned(body=PDF + key.encode())

    env.server.route = route
    return sink


def test_keys_cleaning_to_the_same_name_get_distinct_files(env: Env):
    """Review focus 5: "MOD:X" and "MOD?X" in one folder → two files, no overwrite.
    Review item 7: the names follow CALL order, whoever answers first."""
    sink = _held(env, lambda key, _n: key == "MOD:X")
    report = env.run(keys(KEY_A, KEY_B), index=_Renaming(env, {KEY_A: "MOD:X", KEY_B: "MOD?X"}),
                     sink=sink)
    a, b = report.outcomes
    assert env.events[-1].outcome.key == "MOD:X"  # the first call really answered last
    assert (a.files[0].name, b.files[0].name) == ("MOD_X.pdf", "MOD_X_2.pdf")
    assert (a.files[0].read_bytes(), b.files[0].read_bytes()) == (PDF + b"MOD:X", PDF + b"MOD?X")


def test_same_key_twice_in_one_folder_gets_suffix(env: Env):
    sink = _held(env, lambda _key, n: n == 0)  # whichever is sent first answers last
    report = env.run(keys(KEY_A, KEY_A.lower()), sink=sink)
    assert [o.files[0].name for o in report.outcomes] == [f"{KEY_A}.pdf", f"{KEY_A}_2.pdf"]
    assert all(o.files[0].read_bytes() == PDF + KEY_A.encode() for o in report.outcomes)


def test_names_are_the_same_on_every_run(env: Env):
    """Review item 7: six keys cleaning to one name, run again and again: the
    same names every time, each file holding its own row's answer."""
    spellings = ["MOD:X", "MOD?X", "MOD*X", "MOD<X", "MOD>X", "MOD|X"]
    index = _Renaming(env, dict(zip(KEYS_F, spellings)))
    env.server.route = lambda h, b: Canned(body=PDF + _header(h, "template_key").encode())
    expected = ["MOD_X.pdf"] + [f"MOD_X_{n}.pdf" for n in range(2, 7)]
    for _ in range(5):
        report = env.run(keys(*KEYS_F), index=index)
        assert [o.files[0].name for o in report.outcomes] == expected
        for o in report.outcomes:
            assert o.files[0].read_bytes() == PDF + o.key.encode()
    assert parts(env.tmp_path) == []


def test_a_failed_row_keeps_its_reserved_name(env: Env):
    """Names are reserved before the calls: the failed first row leaves a gap."""
    env.server.route = by_key(**{"MOD:X": Canned(status=500)})
    report = env.run(keys(KEY_A, KEY_B), index=_Renaming(env, {KEY_A: "MOD:X", KEY_B: "MOD?X"}))
    a, b = report.outcomes
    assert (a.status, b.status) == ("failed", "ok") and b.files[0].name == "MOD_X_2.pdf"


def test_package_named_like_the_run_files(env: Env):
    """A package "esito.csv" and a package "111_PKG.zip" next to "111_PKG"
    break neither esito.csv nor the zips."""
    elenco = Elenco(rows=(ElencoRow(KEY_A, "esito.csv"), ElencoRow(KEY_B, "111_PKG"),
                          ElencoRow(KEY_C, "111_PKG.zip")), skipped=0)
    report = env.run(targets_from_keys([KEY_A, KEY_B, KEY_C], elenco), make_zip=True)
    assert [o.status for o in report.outcomes] == ["ok"] * 3
    assert report.outcomes[0].files == (env.run_dir / "_esito.csv" / f"{KEY_A}.pdf",)
    assert (env.run_dir / "esito.csv").is_file() and len(esito_rows(env.run_dir)) == 3
    assert sorted(z.name for z in report.zips) == ["111_PKG.zip.zip", "111_PKG_2.zip", "_esito.csv.zip"]
    assert all(z.is_file() for z in report.zips) and (env.run_dir / "111_PKG.zip").is_dir()


def test_zip_created_when_requested(env: Env):
    elenco = Elenco(rows=(ElencoRow(KEY_A, "111_PKG"), ElencoRow(KEY_B, "222_PKG")), skipped=0)
    report = env.run(targets_from_keys([KEY_A, KEY_B], elenco), make_zip=True)
    assert report.zips == (env.run_dir / "111_PKG.zip", env.run_dir / "222_PKG.zip")
    assert all(z.is_file() for z in report.zips)
    assert env.run(keys(KEY_A)).zips == ()  # not asked


def test_two_runs_in_the_same_second_get_two_folders(env: Env):
    first, second = env.run(keys(KEY_A)), env.run(keys(KEY_A))
    assert first.run_dir == env.run_dir and second.run_dir == env.destination / f"{RUN}_2"
    assert first.outcomes[0].files[0].name == second.outcomes[0].files[0].name == f"{KEY_A}.pdf"


# ----------------------------------------------------------------- failures ---

def test_http_500_is_failed_and_batch_continues(env: Env):
    env.server.route = by_key(**{KEY_B: Canned(status=500, body=f"errore {SECRET} {sas()}".encode())})
    report = env.run(keys(KEY_A, KEY_B, KEY_C))
    a, b, c = report.outcomes
    assert (a.status, b.status, c.status) == ("ok", "failed", "ok")
    assert b.http_status == 500 and "HTTP 500" in b.reason and b.files == ()
    assert SECRET not in b.reason and SIG not in b.reason  # the reason, never the body
    assert len(env.server.requests) == 3
    esito = (env.run_dir / "esito.csv").read_text(encoding="utf-8-sig")
    assert SECRET not in esito and SIG not in esito


def test_unrecognised_body_is_failed(env: Env):
    env.server.route = by_key(**{KEY_A: Canned(body=b'{"status": "KO"}')})
    (o,) = env.run(keys(KEY_A)).outcomes
    assert (o.status, o.reason, o.http_status, o.files) == ("failed", REASON_NOT_A_DOCUMENT, 200, ())
    assert not (env.run_dir / NO_PACKAGE).exists()


def test_unreadable_payload_is_failed(env: Env):
    (o,) = env.run(keys(KEY_BAD)).outcomes
    assert (o.status, o.reason) == ("failed", "payload non leggibile")
    assert env.server.requests == []


def test_missing_call_is_no_call_and_server_not_hit(env: Env):
    report = env.run(keys("MOD_TEST_ZZZ") + targets_from_fdis(["dddddddd-1111-4222-8333-444444444444"]))
    assert [(o.status, o.reason) for o in report.outcomes] == [
        ("no_call", "nessuna chiamata nei log di coll")] * 2
    assert env.server.requests == []
    assert [r[3] for r in esito_rows(env.run_dir)] == ["nessuna chiamata nei log"] * 2


@pytest.mark.parametrize("where", ["a file", "under a file", "too long"])
def test_run_folder_that_cannot_be_made_refuses_before_any_call(env: Env, tmp_path: Path, where):
    """Review item 5: every call used to be sent, then every document thrown away."""
    blocker = tmp_path / "un_file"
    blocker.write_text("non una cartella", encoding="utf-8")
    env.destination = {"a file": blocker, "under a file": blocker / "sotto",
                       "too long": tmp_path / ("d" * 300)}[where]  # over a component's limit
    with pytest.raises(ValueError, match="impossibile creare la cartella della generazione"):
        env.run(keys(KEY_A, KEY_B))
    assert env.server.requests == [] and env.events == []
    assert parts(tmp_path) == []


def test_generator_disabled_during_the_run_gets_nothing_more(env: Env):
    """Review item 3b: the rows not yet sent re-check the CURRENT settings."""
    def disable() -> None:
        env.settings = dataclasses.replace(env.settings, generators=[
            dataclasses.replace(g, enabled=False) for g in env.settings.generators])

    on_the_wire = threading.Barrier(WORKERS, action=disable, timeout=10)

    def route(headers, body):
        on_the_wire.wait()  # every lane busy → disabled in "Impostazioni", then they answer
        return Canned()

    env.server.route = route
    report = env.run(keys(*KEYS_F))
    statuses = [o.status for o in report.outcomes]
    assert statuses == ["ok"] * WORKERS + ["failed"] * (len(KEYS_F) - WORKERS)
    assert all(o.reason == reason_generator_gone("svil") for o in report.outcomes[WORKERS:])
    assert len(env.server.requests) == WORKERS


def test_cancel_during_lookup_creates_nothing(env: Env):
    """Small item: no run folder holding only an all-"annullato" esito.csv."""
    cancel = CancelToken()
    cancel.cancel()
    report = env.run(keys(KEY_A, KEY_B), cancel=cancel)
    assert report.cancelled and [o.status for o in report.outcomes] == ["cancelled"] * 2
    assert report.run_dir == env.run_dir and not env.destination.exists()


# ------------------------------------------------------------------- count ---

def test_count_is_the_calls_that_would_be_sent(env: Env):
    """Review item 6: an FDI is as many calls as its keys; nothing is created."""
    env.memory.record(KEY_D, "html")
    targets = targets_from_fdis([FDI_A, FDI_B, "dddddddd-1111-4222-8333-444444444444"])
    assert env.count(targets) == 3 + 9 - 1  # FDI_B: 9 keys, one known HTML; the unknown: none
    assert env.count(targets, save_html=True) == 3 + 9
    assert env.count(keys(KEY_A, "MOD_TEST_ZZZ")) == 1
    assert env.server.requests == [] and not env.destination.exists()


def test_count_refuses_like_the_run_and_stops_on_cancel(env: Env):
    from qtrequestory.core.events import Cancelled

    with pytest.raises(ValueError, match="assoluto"):
        env.count(keys(KEY_A), destination=Path("relativa"))
    cancel = CancelToken()
    cancel.cancel()
    with pytest.raises(Cancelled):
        env.count(targets_from_fdis([FDI_A]), cancel=cancel)


# ------------------------------------------------------------------- retry ---

def test_retry_of_one_key_of_an_fdi_sends_only_that_key(env: Env):
    """Review item 1: FDI A, B, C where only B failed → the retry target (what
    ``ui.pages.genera_retry`` builds) sends B only, from that FDI's own call,
    into the FDI's folder."""
    env.server.route = by_key(**{KEY_B: Canned(status=500)})
    first = env.run(targets_from_fdis([FDI_A]))
    assert sorted((o.key, o.status) for o in first.outcomes) == [
        (KEY_A, "ok"), (KEY_B, "failed"), (KEY_C, "ok")]
    env.server.requests.clear()
    env.server.route = None
    (again,) = env.run([Target("fdi", FDI_A, (), (KEY_B,))]).outcomes
    assert [_header(h, "template_key") for h, _ in env.server.requests] == [KEY_B]
    assert (again.key, again.status, again.fdi, again.folders) == (KEY_B, "ok", FDI_A, (FDI_A,))
    assert again.files[0].parent.name == FDI_A


def test_disk_full_midway_fails_row_and_continues(env: Env, monkeypatch: pytest.MonkeyPatch):
    """Review focus 3: the row fails with its reason, the others are saved, esito is written."""
    real = output._write_bytes

    def full_for_b(path: Path, content: bytes) -> None:
        if KEY_B in path.name:
            real(path, content[:10])
            raise OSError(28, "No space left on device")
        real(path, content)

    monkeypatch.setattr(output, "_write_bytes", full_for_b)
    report = env.run(keys(KEY_A, KEY_B, KEY_C))
    assert [o.status for o in report.outcomes] == ["ok", "failed", "ok"]
    assert "scrittura non riuscita" in report.outcomes[1].reason
    assert [r[3] for r in esito_rows(env.run_dir)] == ["ok", "non riuscito", "ok"]
    assert parts(env.tmp_path) == [] and not (env.run_dir / NO_PACKAGE / f"{KEY_B}.pdf").exists()


def test_esito_failure_does_not_lose_the_report(env: Env, monkeypatch: pytest.MonkeyPatch, caplog):
    def broken(run_dir, outcomes):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr("qtrequestory.officina.batch.runner.write_esito", broken)
    with caplog.at_level(logging.WARNING):
        report = env.run(keys(KEY_A), make_zip=True)
    assert report.outcomes[0].status == "ok" and "esito.csv non scritto" in caplog.text


# ------------------------------------------------------------------- HTML ---

def test_html_skipped_when_not_requested_and_remembered(env: Env):
    env.server.route = by_key(**{KEY_A: Canned(body=HTML)})
    (o,) = env.run(keys(KEY_A)).outcomes
    assert (o.status, o.doc_type, o.reason, o.files) == ("html_skipped", "html", "HTML non richiesto", ())
    assert env.memory.is_html(KEY_A) and len(env.server.requests) == 1
    assert esito_rows(env.run_dir)[0][3] == "saltato: HTML"


def test_remembered_html_not_called_next_time(env: Env):
    env.memory.record(KEY_A, "html")
    (o,) = env.run(keys(KEY_A)).outcomes
    assert (o.status, o.reason) == ("html_skipped", "HTML già noto: non richiesto")
    assert env.server.requests == []
    # asked for the HTML: called again, and a PDF answer takes the key out of the memory
    (o,) = env.run(keys(KEY_A), save_html=True).outcomes
    assert o.status == "ok" and not env.memory.is_html(KEY_A)


def test_html_saved_when_requested(env: Env):
    env.server.route = by_key(**{KEY_A: Canned(body=HTML)})
    (o,) = env.run(keys(KEY_A), save_html=True).outcomes
    assert o.status == "ok" and o.files == (env.run_dir / NO_PACKAGE / f"{KEY_A}.html",)
    assert o.files[0].read_bytes() == HTML and env.memory.is_html(KEY_A)


# ---------------------------------------------------------------- headers ---

def _header(headers: dict[str, str], name: str) -> str | None:
    return next((v for k, v in headers.items() if k.casefold() == name.casefold()), None)


def test_headers_on_the_wire_follow_rows(env: Env):
    rows = [r for r in default_rows(env.settings) if r[0] != "Postman-Token"] + [("IMEL", "active")]
    env.run(keys(KEY_A.lower()), header_rows=tuple(rows))
    ((headers, body),) = env.server.requests
    assert _header(headers, "imel") == "active"
    assert _header(headers, "postman-token") is None
    assert _header(headers, "template_key") == KEY_A  # the spelling of the logs
    assert _header(headers, "correlation_id") == "uuid-1"
    assert _header(headers, "current_timestamp") == str(int(NOW.astimezone().timestamp() * 1000))
    assert _header(headers, "office_id") == "00001"
    assert json.loads(body)["documents"][0]["template"]["templateKey"] == KEY_A  # sent as logged


def test_invalid_header_raises_before_any_call(env: Env):
    rows = tuple(default_rows(env.settings)) + (("IMEL", "a\nb"),)
    with pytest.raises(ValueError, match="intestazioni"):
        env.run(keys(KEY_A), header_rows=rows)
    assert env.server.requests == [] and not env.destination.exists() and env.events == []


@pytest.mark.parametrize("generators, name", [
    ([GeneratorEndpoint("svil", "x", enabled=False), GeneratorEndpoint("coll", "x")], "svil"),
    ([GeneratorEndpoint("PRODUZIONE", "x")], "PRODUZIONE"),
    ([GeneratorEndpoint("coll", "x")], "svil"),
])
def test_disabled_generator_raises_value_error(env: Env, generators, name):
    env.settings.generators = [dataclasses.replace(g, url=env.server.url) for g in generators]
    with pytest.raises(ValueError):
        env.run(keys(KEY_A), generator=name)
    assert env.server.requests == [] and not env.destination.exists()


def test_index_that_cannot_be_searched_raises_value_error(env: Env):
    class Broken(RealIndex):
        def search(self, query):
            raise sqlite3.OperationalError("database is locked")

    with pytest.raises(ValueError, match="ricerca delle chiamate non riuscita"):
        env.run(keys(KEY_A), index=Broken(env.index.conn, env.index.root))
    assert env.server.requests == [] and not env.destination.exists()


def test_unexpected_error_in_a_row_is_failed_with_its_type_only(env: Env,
                                                                monkeypatch: pytest.MonkeyPatch):
    real = env.memory.is_html

    def is_html(key: str) -> bool:
        if key == KEY_B:
            raise RuntimeError(f"bug con {SECRET}")
        return real(key)

    monkeypatch.setattr(env.memory, "is_html", is_html)
    a, b = env.run(keys(KEY_A, KEY_B)).outcomes
    assert a.status == "ok"
    assert (b.status, b.reason) == ("failed", "errore inatteso: RuntimeError")


def test_relative_destination_raises_value_error(env: Env):
    env.destination = Path("relativa")
    with pytest.raises(ValueError, match="assoluto"):
        env.run(keys(KEY_A))
    assert env.server.requests == []


# ------------------------------------------------------- order and events ---

def test_events_total_and_one_per_item(env: Env):
    threads: list[threading.Thread] = []

    def sink(event) -> None:
        threads.append(threading.current_thread())
        env.events.append(event)

    report = env.run(keys(KEY_A, KEY_B, "MOD_TEST_ZZZ"), sink=sink)
    started, *items = env.events
    assert started == BatchStarted(3)
    assert all(isinstance(e, BatchItemDone) and e.total == 3 for e in items)
    assert [e.done for e in items] == [1, 2, 3]
    assert sorted(e.outcome.key for e in items) == sorted(o.key for o in report.outcomes)
    assert set(threads) == {threading.current_thread()}  # never from a worker


def test_a_failing_sink_does_not_break_the_run(env: Env):
    def sink(event) -> None:
        raise RuntimeError("finestra chiusa")

    report = env.run(keys(KEY_A, KEY_B), sink=sink)
    assert [o.status for o in report.outcomes] == ["ok", "ok"]


def test_outcomes_keep_request_order(env: Env):
    release = threading.Event()

    def route(headers, body):
        if _header(headers, "template_key") == KEY_A:
            assert release.wait(10)  # A answers only once B and C are done
        return Canned()

    def sink(event) -> None:
        env.events.append(event)
        if sum(isinstance(e, BatchItemDone) for e in env.events) == 2:
            release.set()

    env.server.route = route
    report = env.run(keys(KEY_A, KEY_B, KEY_C), sink=sink)
    assert [o.key for o in report.outcomes] == [KEY_A, KEY_B, KEY_C]
    assert env.events[-1].outcome.key == KEY_A  # it completed last
    assert [r[0] for r in esito_rows(env.run_dir)] == [KEY_A, KEY_B, KEY_C]


# ---------------------------------------------------------------- cancel ---

def test_cancel_midway_marks_rest_cancelled_and_writes_esito(env: Env):
    """Review focus 4: the calls on the wire finish and are saved, the rest is
    "annullato", esito.csv is written, no zip, no .part left."""
    cancel = CancelToken()
    on_the_wire = threading.Barrier(WORKERS, action=cancel.cancel, timeout=10)

    def route(headers, body):
        on_the_wire.wait()  # all lanes busy → cancel, then they answer
        return Canned()

    env.server.route = route
    report = env.run(keys(*KEYS_F), cancel=cancel, make_zip=True)
    statuses = [o.status for o in report.outcomes]
    assert statuses == ["ok"] * WORKERS + ["cancelled"] * (len(KEYS_F) - WORKERS)
    assert all(o.files and o.files[0].is_file() for o in report.outcomes[:WORKERS])
    assert report.cancelled and report.zips == () and len(env.server.requests) == WORKERS
    assert [r[3] for r in esito_rows(env.run_dir)] == ["ok"] * 3 + ["annullato"] * 3
    assert not list(env.run_dir.glob("*.zip")) and parts(env.tmp_path) == []
    assert sum(isinstance(e, BatchItemDone) for e in env.events) == len(KEYS_F)


def test_cancel_during_resolution_reports_every_target(env: Env):
    cancel = CancelToken()

    class CancelAfterFirst(RealIndex):
        def search(self, query):
            hits = super().search(query)
            cancel.cancel()
            return hits

    targets = keys(KEY_A) + targets_from_fdis([FDI_A]) + keys(KEY_B)
    report = env.run(targets, cancel=cancel, index=CancelAfterFirst(env.index.conn, env.index.root))
    assert report.cancelled
    assert [(o.key, o.folders, o.status) for o in report.outcomes] == [
        (KEY_A, (NO_PACKAGE,), "cancelled"), ("", (FDI_A,), "cancelled"),
        (KEY_B, (NO_PACKAGE,), "cancelled")]
    assert report.outcomes[1].fdi == FDI_A
    # nothing was sent: no run folder, no esito.csv (the report says where it would have been)
    assert env.server.requests == [] and not env.destination.exists()
    assert report.run_dir == env.run_dir


# ---------------------------------------------------------------- privacy ---

def test_nothing_sensitive_reaches_logs_events_or_esito(env: Env, caplog):
    env.server.route = by_key(**{KEY_SECRET: Canned(status=502, body=f"{SECRET} {sas()}".encode())})
    rows = tuple(default_rows(env.settings)) + (("x-api-key", "SEGRETO_HEADER"),)
    with caplog.at_level(logging.DEBUG):
        report = env.run(keys(KEY_SECRET, KEY_A), header_rows=rows)
    assert [o.status for o in report.outcomes] == ["failed", "ok"]
    sent = [(h, b) for h, b in env.server.requests if _header(h, "template_key") == KEY_SECRET]
    ((secret_headers, secret_body),) = sent
    assert SECRET.encode() in secret_body  # the payload and headers did go out as they are...
    assert _header(secret_headers, "x-api-key") == "SEGRETO_HEADER"
    leaks = [caplog.text, repr(env.events), repr(report),
             (env.run_dir / "esito.csv").read_text(encoding="utf-8-sig")]
    for text in leaks:  # ...but nowhere else
        assert SECRET not in text and SIG not in text and "SEGRETO_HEADER" not in text
