"""The control generation of ``OfficinaService`` (phase 2.5, spec §3.4,
decision D14): automatic, in the background, silent on errors, never a version.

**When.** After a successful generation of a case (``generate``: the AS-IS
or a TO-BE) whose payload has no usable control yet — the first generation,
the first one after "Sostituisci la chiamata" (the old control belongs to the
old payload and stops being used: there is no document of the new call to
compare with before its first generation), the next one after a control
that failed. A generation that starts CANCELS the control of its case in
progress (a call already under way runs to its end; its answer is dropped),
and at most one control runs per case: a new one waits for the cancelled
one's call to end.

**What.** A copy of the payload with the safe perturbation of
``officina.control`` goes to the SVIL generator (spec §3.4, D11: the
configured, enabled generator named "svil", whatever the case's own
generator; none → ``non_disponibile``) with the headers of the case
(``generator.resolve_headers``: the Postman-Token included, like any
generation) through ``generator.send``. The upload link (``attachmentUrl``)
goes as it is: the generator may refuse a job without it; the blob it names
is then last written with the control document, which the app never reads
(versions come only from the HTTP answer). The answer must be a PDF with
the same pages and sections as the generation (else the job retries without
half of the leaves: ``control.subsets``, at most :data:`MAX_CALLS` calls; a
4xx answer — a validation the perturbation tripped — is retried the same
way; a 5xx, a timeout or a network error stops at once). Only the printed
forms of the perturbed values are the ``esecuzione`` proof
(``control.proven_words``, ruling F18).

**Where.** Never in ``asis\\`` or ``tobe\\``: the answer is
``<case>\\cache\\controllo-<sha>.pdf``, next to ``controllo-<sha>.json``
(the reference version, its content hash and the changed words), ``<sha>``
being ``filter_model.control_sha(generated document, payload)``; the state is
the ``controllo`` record of ``caso.json`` (``pronta`` / ``non_disponibile``;
``in_corso`` only in memory). A control stops being used as soon as its
reference version is gone or changed, or the payload changed.

**A deleted initiative** (final review I1): :meth:`ControlMixin.cancel_controls`
(called by ``delete_initiative`` before the folder goes) cancels its
controls, and a job writes nothing once its case's ``caso.json`` is gone —
it never creates a folder (``cache`` only inside an existing case folder,
files without parents), so no "ghost" initiative folder is left behind.

**Errors** (HTTP, timeout, network, an answer that is not a PDF, the
structure changed every time, anything unexpected): one line in the log,
the record ``non_disponibile`` (the panel's discreet note), never an
exception, never a message to the user.

**Use.** :meth:`ControlMixin._executed` gives ``compare_case`` the proof of
each compared version: the reference's own changed words, carried onto a
later version of the same payload by ``control.map_executed``.

Stdlib only at import time.
"""
from __future__ import annotations

import dataclasses
import hashlib
import logging
import os
import threading
import uuid
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from qtrequestory.core.fsutil import remove_quietly, replace_with_retry
from qtrequestory.officina.compare.extract_pdf import DocText, extract
from qtrequestory.officina.compare.filter_model import ControlState, control_sha
from qtrequestory.officina.compare.pipeline import compare_docs
from qtrequestory.officina.compare.values import WordKey
from qtrequestory.officina.control import perturb, structure_changed, subsets, visible_leaves
from qtrequestory.officina.control_proof import map_executed, proven_words
from qtrequestory.officina.generator import resolve_headers, send
from qtrequestory.officina.links import mask_text_for_log
from qtrequestory.officina.model import Case, Initiative, Version
from qtrequestory.officina.model_case import case_write_lock
from qtrequestory.officina.model_io import read_json_object, read_json_strict, write_bytes_atomic, write_json_atomic
from qtrequestory.officina.model_review import ControlRecord, Review

__all__ = ["MAX_CALLS", "ControlMixin", "ControlRunner", "start_thread"]

log = logging.getLogger("qtrequestory.officina.service")

#: Starts a job in the background; ``None`` in the service = no control generation.
ControlRunner = Callable[[Callable[[], None]], Any]
#: Generations one control may cost (all the leaves, then each half).
MAX_CALLS = 3
#: The generator a control generation goes to (spec §3.4).
CONTROL_GENERATOR = "svil"


def start_thread(job: Callable[[], None]) -> threading.Thread:
    """The default runner: a daemon thread per control (never blocks closing the app)."""
    thread = threading.Thread(target=job, name="officina-controllo", daemon=True)
    thread.start()
    return thread


class _Cancelled(Exception):
    pass


class _Job:
    def __init__(self, since: str) -> None:
        self.cancel = threading.Event()
        self.done = threading.Event()
        self.since = since


def _key(case: Case) -> str:
    return str(Path(case.folder).resolve()).lower()


class ControlMixin:
    """Needs ``_workspace()``, ``_settings()``, ``_clock()``, ``_new_uuid``,
    ``_opener``, ``_now()``, ``_fresh_review()``, ``_input()``; call
    :meth:`_init_control` from the service's ``__init__``."""

    def _init_control(self, runner: ControlRunner | None) -> None:
        self._control_runner = runner
        self._control_lock = threading.Lock()
        self._control_jobs: dict[str, _Job] = {}

    # ------------------------------------------------------------- state ---

    def control_state(self, case: Case) -> ControlState:
        """``in_corso`` while a job runs; else the ``controllo`` record of
        ``caso.json`` (read alone, not the whole case) — a ``pronta`` record
        no longer usable with the case's payload (the call was replaced, the
        reference version changed) reads ``assente``. Never raises."""
        with self._control_lock:
            job = self._control_jobs.get(_key(case))
        if job is not None and not job.cancel.is_set():
            return ControlState("in_corso", quando=job.since)
        try:
            record = ControlRecord.from_json(read_json_object(case.folder / "caso.json").get("controllo"))
            if record is not None and record.stato == "pronta":
                payload = read_json_object(case.folder / "payload.json")
                if self._reference(case, record, payload) is None:
                    return ControlState("assente")
        except Exception:  # noqa: BLE001 - never raises (contract)
            record = None
        return record.state() if record is not None else ControlState("assente")

    def cancel_controls(self, ini: Initiative) -> None:
        """Cancel every control in progress of ``ini``'s cases (its folder is
        about to be deleted): their answers are dropped, nothing is written."""
        inside = os.path.join(str(Path(ini.folder).resolve()).lower(), "")
        with self._control_lock:
            jobs = [job for key, job in self._control_jobs.items() if key.startswith(inside)]
        for job in jobs:
            job.cancel.set()

    def _cancel_control(self, case: Case) -> None:
        """A generation of ``case`` starts: its control in progress is dropped."""
        with self._control_lock:
            job = self._control_jobs.get(_key(case))
        if job is not None:
            job.cancel.set()

    # ------------------------------------------------------------- start ---

    def _start_control(self, ini: Initiative, case: Case, version: Version, payload: dict) -> None:
        """After ``version`` of ``case`` was generated from ``payload``: start
        a control unless a usable one exists. Never raises."""
        if self._control_runner is None:
            return
        try:
            if version.doc_type != "pdf":
                return  # an email body has no control generation (spec §3.4: a PDF answer)
            review = self._fresh_review(case)  # type: ignore[attr-defined]
            record = review.control
            if record is not None and record.stato == "pronta" and self._reference(case, record, payload):
                return
            data = version.path.read_bytes()
            sha = control_sha(data, payload)
            job = _Job(self._now())  # type: ignore[attr-defined]
            with self._control_lock:
                previous = self._control_jobs.get(_key(case))
                if previous is not None:
                    previous.cancel.set()
                self._control_jobs[_key(case)] = job
            self._control_runner(lambda: self._control_run(ini, case, version, data, payload, sha, job, previous))
        except Exception as exc:  # noqa: BLE001 - D14: never an error for the user
            log.warning("Officina: %s: generazione di controllo non avviata (%s)", case.id, type(exc).__name__)

    # --------------------------------------------------------------- job ---

    def _control_run(self, ini: Initiative, case: Case, version: Version, data: bytes, payload: dict, sha: str,
                     job: _Job, previous: _Job | None) -> None:
        outcome: tuple[str, frozenset[WordKey], bytes, str] | None = None
        try:
            if previous is not None:  # one call per case at a time
                previous.done.wait(self._settings().timeout_s + 5)  # type: ignore[attr-defined]
            outcome = self._control_attempts(ini, case, version, payload, sha, job)
        except _Cancelled:
            outcome = None
        except Exception as exc:  # noqa: BLE001 - D14: silent
            outcome = ("non_disponibile", frozenset(), b"", f"errore inatteso: {type(exc).__name__}")
        try:
            if outcome is not None:
                self._control_finish(case, version, data, sha, outcome, job)
        except Exception as exc:  # noqa: BLE001
            log.warning("Officina: %s: esito della generazione di controllo non salvato (%s)", case.id,
                        type(exc).__name__)
        finally:
            with self._control_lock:
                if self._control_jobs.get(_key(case)) is job:
                    del self._control_jobs[_key(case)]
            job.done.set()

    @staticmethod
    def _check(job: _Job) -> None:
        if job.cancel.is_set():
            raise _Cancelled

    def _control_url(self) -> str | None:
        """The URL of the svil generator, or None when it is not usable."""
        from qtrequestory.officina.service import _enabled_generator  # the service's own checks

        endpoint, problem = _enabled_generator(self._settings(), CONTROL_GENERATOR)  # type: ignore[attr-defined]
        return None if problem else endpoint.url

    def _control_attempts(self, ini: Initiative, case: Case, version: Version, payload: dict,
                          sha: str, job: _Job) -> tuple[str, frozenset[WordKey], bytes, str]:
        self._check(job)
        url = self._control_url()
        if url is None:
            return "non_disponibile", frozenset(), b"", "generatore svil non configurato o non attivo"
        reference = self._input(version).doc  # type: ignore[attr-defined]
        if not isinstance(reference, DocText) or not reference.has_text:
            return "non_disponibile", frozenset(), b"", "documento senza testo"
        leaves = visible_leaves(payload, reference.words)
        why = "nessun valore del payload è stampato nel documento"
        for group in subsets(leaves, MAX_CALLS):
            self._check(job)
            perturbed, changed = perturb(payload, group, sha)
            if not changed:
                continue
            settings = self._settings()  # type: ignore[attr-defined]
            now = self._clock()  # type: ignore[attr-defined]
            headers = resolve_headers(case, ini, settings, now_ms=int(now.timestamp() * 1000),
                                      new_uuid=self._new_uuid, source_fdi=case.source_fdi)  # type: ignore[attr-defined]
            result = send(url, perturbed, headers, timeout_s=settings.timeout_s,
                          opener=self._opener)  # type: ignore[attr-defined]
            self._check(job)
            if not result.ok and result.status is not None and 400 <= result.status < 500:
                why = f"il generatore ha risposto HTTP {result.status} al payload modificato"
                continue  # a validation the perturbation tripped: fewer leaves (never a 5xx: a server down)
            if not result.ok:
                return "non_disponibile", frozenset(), b"", result.reason
            if result.doc_type != "pdf":
                return "non_disponibile", frozenset(), b"", "la risposta non è un PDF"
            comparison = compare_docs(reference, self._control_doc(case, result.content))
            if structure_changed(comparison):
                why = "il payload modificato cambia pagine o sezioni del documento"
                continue
            proven = proven_words(comparison, [(leaf.value, new) for leaf, new in changed])
            return "pronta", proven, result.content, ""
        return "non_disponibile", frozenset(), b"", why

    @staticmethod
    def _control_doc(case: Case, content: bytes) -> DocText:
        """The words of a control answer (extracted from a private file in the
        case cache; ``_Cancelled`` when the case is gone: never a new folder)."""
        if not (case.folder / "caso.json").is_file():
            raise _Cancelled
        cache = case.folder / "cache"
        try:
            cache.mkdir(exist_ok=True)
        except FileNotFoundError:
            raise _Cancelled from None
        path = cache / f"controllo-{uuid.uuid4().hex[:12]}.tmp.pdf"
        try:
            path.write_bytes(content)
            return extract(path)
        finally:
            remove_quietly(path)

    def _control_finish(self, case: Case, version: Version, data: bytes, sha: str,
                        outcome: tuple[str, frozenset[WordKey], bytes, str], job: _Job) -> None:
        """``data``: the bytes ``sha`` was made from (the reference version's).
        Under the case's write lock: nothing when ``job`` was cancelled or the
        case is gone (``caso.json`` missing); never creates a folder."""
        stato, executed, content, why = outcome
        cache = case.folder / "cache"
        with case_write_lock(case.folder):
            if job.cancel.is_set() or not (case.folder / "caso.json").is_file():
                return
            if stato == "pronta":
                cache.mkdir(exist_ok=True)
                write_bytes_atomic(cache / f"controllo-{sha}.pdf", content, make_parents=False)
                write_json_atomic(cache / f"controllo-{sha}.json", {
                    "kind": version.kind, "number": version.number, "doc_sha": hashlib.sha256(data).hexdigest(),
                    "parole": sorted([list(k) for k in executed]),
                }, make_parents=False)
                log.info("Officina: %s: generazione di controllo pronta (%d valori provati)", case.id, len(executed))
            else:
                log.info("Officina: %s: generazione di controllo non disponibile: %s", case.id,
                         mask_text_for_log(why))
            record = ControlRecord(sha, stato, self._now())  # type: ignore[arg-type,attr-defined]
            before = self._write_control(case, record)
        if before is not None and before.sha != sha:
            for name in (f"controllo-{before.sha}.pdf", f"controllo-{before.sha}.json"):
                if len(before.sha) == 64 and all(c in "0123456789abcdef" for c in before.sha):
                    remove_quietly(cache / name)

    def _write_control(self, case: Case, record: ControlRecord) -> ControlRecord | None:
        """Save ``record`` onto the review ON DISK (under the case's write
        lock); ``case`` in hand is not touched (another thread's object).
        The record it replaced."""
        with case_write_lock(case.folder):
            fresh: Review = self._fresh_review(case)  # type: ignore[attr-defined]
            self._workspace().save_review(  # type: ignore[attr-defined]
                dataclasses.replace(case, review=dataclasses.replace(fresh, control=record)))
        return fresh.control

    # --------------------------------------------------------------- use ---

    def _reference(self, case: Case, record: ControlRecord, payload: object
                   ) -> tuple[Version, str, frozenset[WordKey]] | None:
        """``(reference version, its content hash, changed words)`` of a
        ``pronta`` control still usable with ``payload``; None otherwise."""
        try:
            cache = case.folder / "cache"
            side = read_json_strict(cache / f"controllo-{record.sha}.json")
            if not (cache / f"controllo-{record.sha}.pdf").is_file():
                return None
            kind, number = side.get("kind"), side.get("number")
            if kind == "asis":
                version = case.asis()
            else:
                version = next((v for v in case.tobe_versions() if v.number == number), None)
            if version is None or version.missing or version.doc_type != "pdf":
                return None
            data = version.path.read_bytes()
            doc_sha = hashlib.sha256(data).hexdigest()
            if doc_sha != side.get("doc_sha") or control_sha(data, payload) != record.sha:
                return None
            words = frozenset((int(p), float(x), float(y), str(t)) for p, x, y, t in side.get("parole") or [])
            return version, doc_sha, words
        except (OSError, ValueError, TypeError, AttributeError):
            return None

    def _executed(self, case: Case, review: Review, payload: object, inputs: Mapping[str, Any]
                  ) -> dict[str, frozenset[WordKey]]:
        """Per label of ``inputs`` (``CaseInput`` s): the generated words the
        case's control proved (``esecuzione``); empty without a usable one."""
        record = review.control
        if record is None or record.stato != "pronta":
            return {}
        found = self._reference(case, record, payload)
        if found is None:
            return {}
        version, doc_sha, executed = found
        try:
            reference = self._input(version).doc  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001 - a proof less, never an error
            return {}
        out: dict[str, frozenset[WordKey]] = {}
        for label, item in inputs.items():
            if item is None or not isinstance(item.doc, DocText) or not isinstance(reference, DocText):
                continue
            out[label] = executed if item.sha == doc_sha else map_executed(reference.words, item.doc.words, executed)
        return out
