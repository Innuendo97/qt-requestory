"""``OfficinaService``: the Officina behind ``ui/contracts.OfficinaApi``.

The UI never touches the model, the generator or the comparison engine
directly: it calls this one object, which binds them to the current
configuration (``Config.officina``, read through a callable on every call so
Impostazioni changes are seen at once).

**Generation** (:meth:`OfficinaService.generate`), in this order, refusing as
early as possible so nothing leaves the machine when it should not:

1. the case's ``env`` must name an *enabled* generator (never anything that
   looks like PROD, whatever the configuration says);
2. an AS-IS that exists is only replaced with a note (checked before sending);
3. the headers are resolved (``generator.resolve_headers``), the correlation
   id from the case's source FDI when the case asks for it;
4. the upload-link policy is applied (``generator.prepare_payload``): a
   still-valid link is never sent;
5. ``generator.send``; its answer must also be of the type the case expects
   (the TARGET's type, else the AS-IS's; with neither, PDF or HTML) — an HTML
   page for a PDF case is almost always a gateway error page;
6. only then is a version written. A failed or refused run writes nothing and
   comes back as ``(None, SendResult(ok=False, reason=...))``.

The service logs outcomes only: case id, slot, environment, status, duration
and the (already masked) reason. Never the payload, the document, the headers
or an unmasked link.

**Comparison** (:meth:`OfficinaService.compare`, :meth:`render_path`): in
``officina.service_compare`` (the text engine, Edge's HTML print and their
caches); see its docstring.

Stdlib only at import time: ``compare.extract_pdf`` loads pypdfium2 inside
``extract()``, so importing this module keeps the lazy boundary.
"""
from __future__ import annotations

import dataclasses
import json
import logging
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from qtrequestory.core.config import Config, OfficinaSettings, generator_url_problem, is_prod_like
from qtrequestory.core.index.search import IndexStale
from qtrequestory.officina import delivery as _delivery
from qtrequestory.officina.compare.edge import html_to_pdf as edge_html_to_pdf
from qtrequestory.officina.delivery import DeliveryPlan, DeliveryReport
from qtrequestory.officina.generator import (
    PREVIEW_BYTES,
    HeaderError,
    SendResult,
    prepare_payload,
    resolve_headers,
    send,
)
from qtrequestory.officina.links import find_links, mask, mask_bytes, mask_text, mask_text_for_log
from qtrequestory.officina.model import AsisAlreadyExistsError, Case, Initiative, Version, Workspace
from qtrequestory.officina.service_compare import EDGE_TIMEOUT_S, CompareError, CompareMixin, HtmlToPdf

if TYPE_CHECKING:
    from qtrequestory.core.index.search import SearchHit

__all__ = ["EDGE_TIMEOUT_S", "CompareError", "OfficinaService"]

log = logging.getLogger(__name__)

REASON_CANCELLED = "generazione annullata prima dell'invio"
REASON_HTML_FOR_PDF = "risposta HTML per un caso PDF: probabilmente una pagina d'errore del gateway"
REASON_PDF_FOR_HTML = ("risposta PDF per un caso HTML: il generatore ha prodotto un documento, "
                       "non il corpo dell'email (controllare template_key e payload)")
REASON_VANISHED_CALL = "la chiamata non è più nel log locale: ripetere la ricerca"

class OfficinaService(CompareMixin):
    """Satisfies ``ui.contracts.OfficinaApi``. Thread-safe: the UI calls it
    from JobRunner workers (the caches are guarded by a lock)."""

    def __init__(
        self,
        config_source: Callable[[], Config],
        *,
        index: Any = None,
        opener: Callable[..., Any] | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        new_uuid: Callable[[], str] = lambda: str(uuid.uuid4()),
        html_to_pdf: HtmlToPdf = edge_html_to_pdf,
    ) -> None:
        self._config_source = config_source
        self._index = index  # an IndexApi: only case_from_hit needs it
        self._opener = opener  # None: generator.send's redirect-refusing opener
        self._clock = clock
        self._new_uuid = new_uuid
        self._init_compare(html_to_pdf)

    # --------------------------------------------------------------- workspace ---

    def _settings(self) -> OfficinaSettings:
        return self._config_source().officina

    def workspace_root(self) -> Path | None:
        """The Officina folder, or None while none is chosen (or it is not an
        absolute path: a relative one would resolve against the process CWD)."""
        root = self._settings().root
        if root is None or not str(root).strip() or not Path(root).is_absolute():
            return None
        return Path(root)

    def _workspace(self) -> Workspace:
        root = self.workspace_root()
        if root is None:
            raise ValueError("cartella dell'Officina non impostata: sceglierla in Impostazioni")
        return Workspace(root)

    def initiatives(self) -> list[Initiative]:
        root = self.workspace_root()
        return Workspace(root).initiatives() if root is not None else []

    def create_initiative(self, name: str) -> Initiative:
        if not name.strip():
            raise ValueError("il nome dell'iniziativa è vuoto")
        return self._workspace().create_initiative(name.strip())

    def load(self, initiative_id: str) -> Initiative:
        """By folder (``Initiative.id``), never by display name."""
        return self._workspace().load(initiative_id)

    def case_from_hit(self, ini: Initiative, hit: SearchHit, variant: str = "") -> Case:
        """A case whose payload is the body of a Ricerca hit; key and FDI come
        from the hit. ``ValueError`` when the body is not a JSON object, or
        when the call is no longer in the local log (``REASON_VANISHED_CALL``)."""
        if self._index is None:
            raise ValueError("ricerca non disponibile: impossibile leggere la chiamata")
        try:
            body = self._index.read_body(hit)
        except (IndexStale, OSError):
            # the daily file was rewritten or deleted since the search
            raise ValueError(REASON_VANISHED_CALL) from None
        payload = _json_object(body, what="il corpo della chiamata")
        return self._add_case(ini, hit.template_key, variant, payload, source_fdi=hit.fdi)

    def case_from_file(self, ini: Initiative, path: Path, key: str, variant: str = "") -> Case:
        """A case whose payload is the JSON file at ``path`` (UTF-8, BOM allowed)."""
        payload = _json_object(Path(path).read_bytes(), what=f"il file {Path(path).name}")
        return self._add_case(ini, key, variant, payload, source_fdi=None)

    def _add_case(self, ini: Initiative, key: str, variant: str, payload: dict, *,
                  source_fdi: str | None) -> Case:
        key = (key or "").strip()
        if not key:
            raise ValueError("manca la template_key del caso")
        env = self._settings().default_generator
        return self._workspace().add_case(ini, key, variant.strip(), payload, env=env,
                                          source_fdi=source_fdi or None)

    def save_case(self, case: Case) -> None:
        self._workspace().save_case(case)

    def payload(self, case: Case) -> dict:
        return self._workspace().payload(case)

    def save_payload(self, case: Case, payload: dict) -> None:
        self._workspace().save_payload(case, payload)

    def set_target(self, case: Case, src: Path) -> Version:
        return self._workspace().set_target(case, Path(src))

    # ---------------------------------------------------------------- generate ---

    def generate(
        self,
        ini: Initiative,
        case: Case,
        kind: Literal["asis", "tobe"],
        *,
        replace_asis_note: str | None = None,
        cancel: Any = None,
    ) -> tuple[Version | None, SendResult]:
        """Generate the AS-IS or a new TO-BE of ``case`` (steps in the module
        docstring). Never raises for a refused or failed run: the reason is in
        the returned ``SendResult``. ``cancel`` (a ``CancelToken``) is checked
        before the call; a call already under way runs to its end."""
        if kind not in ("asis", "tobe"):
            raise ValueError(f"kind non valido: {kind!r}")
        try:
            workspace = self._workspace()
        except ValueError as exc:
            return self._refused(case, kind, str(exc))
        if ini.load_error:
            return self._refused(case, kind, f"{ini.load_error}: gli header predefiniti "
                                             "dell'iniziativa non sono noti, generazione rifiutata")
        if case.load_error:
            return self._refused(case, kind, f"caso.json non è leggibile ({case.load_error}): "
                                             "generazione rifiutata")
        settings = self._settings()

        endpoint, problem = _enabled_generator(settings, case.env)
        if problem:
            return self._refused(case, kind, problem)
        if kind == "asis" and case.asis() is not None and not (replace_asis_note or "").strip():
            return self._refused(case, kind, "esiste già un AS-IS per questo caso: "
                                             "per rigenerarlo serve una nota che spieghi il motivo")
        now = self._clock()
        if now.tzinfo is None:
            now = now.astimezone()
        try:
            headers = resolve_headers(case, ini, settings, now_ms=int(now.timestamp() * 1000),
                                      new_uuid=self._new_uuid, source_fdi=case.source_fdi)
        except HeaderError as exc:
            return self._refused(case, kind, str(exc))
        original = workspace.payload(case)
        if not original:
            return self._refused(case, kind, "payload mancante, vuoto o non leggibile: "
                                             "controllare payload.json del caso")
        to_send, refusal = prepare_payload(original, case.link_policy, now=now)
        if to_send is None:
            return self._refused(case, kind, refusal)
        if cancel is not None and cancel.is_set():
            return self._refused(case, kind, REASON_CANCELLED)

        result = send(endpoint.url, to_send, headers, timeout_s=settings.timeout_s, opener=self._opener)
        if result.ok:
            mismatch = _type_mismatch(result.doc_type, *_expected_type(case, kind))
            if mismatch:
                result = dataclasses.replace(result, ok=False,
                                             content=mask_bytes(result.content[:PREVIEW_BYTES]),
                                             reason=mismatch)
        if not result.ok:
            log.warning("Officina: %s %s su %s non generato (HTTP %s, %d ms): %s",
                        case.id, kind, endpoint.name, result.status, result.duration_ms,
                        mask_text_for_log(result.reason))
            return None, result

        meta = {
            "env": endpoint.name,
            "generator": mask(endpoint.url),
            "status": result.status,
            "duration_ms": result.duration_ms,
            "bytes": len(result.content),
            "sent_at": now.isoformat(),
            "headers_sent": dict(result.headers_sent),
            "link_policy": case.link_policy,
            "links_removed": len(find_links(original)) if case.link_policy == "remove" else 0,
        }
        try:
            version = workspace.add_version(case, kind, result.content, result.doc_type, meta,
                                            replace_asis_note=replace_asis_note)
        except (AsisAlreadyExistsError, OSError, ValueError) as exc:
            reason = mask_text(f"documento ricevuto ma non salvato: {exc}")
            log.warning("Officina: %s %s su %s non salvato: %s", case.id, kind, endpoint.name,
                        mask_text_for_log(reason))
            return None, dataclasses.replace(result, ok=False, content=b"", reason=reason)
        log.info("Officina: %s %s n.%d generato su %s (%s, %d ms)",
                 case.id, kind, version.number, endpoint.name, version.doc_type, result.duration_ms)
        return version, result

    @staticmethod
    def _refused(case: Case, kind: str, reason: str) -> tuple[None, SendResult]:
        log.warning("Officina: %s %s non inviato: %s", case.id, kind, mask_text_for_log(reason))
        reason = mask_text(reason)  # the user still sees which link (masked)
        return None, SendResult(ok=False, status=None, doc_type=None, content=b"", duration_ms=0,
                                reason=reason, headers_sent={})

    # ---------------------------------------------------------------- delivery ---

    def delivery_plan(self, ini: Initiative, case_ids) -> DeliveryPlan:
        return _delivery.build_plan(ini, list(case_ids))

    def delivery_conflicts(self, ini: Initiative, items, destination: Path, *,
                           make_zip: bool) -> list[Path]:
        return _delivery.find_conflicts(list(items), Path(destination), ini.id, make_zip=make_zip)

    def deliver(self, ini: Initiative, items, destination: Path, *, on_conflict,
                make_zip: bool, cancel: Any = None) -> DeliveryReport:
        """Deliver (``officina.delivery.deliver``) and remember the destination.
        The delivery folder is named after the initiative's folder (its
        identity), not its display name. A destination that cannot be
        remembered (``iniziativa.json`` unreadable: never written over) is
        said in ``report.remember_problem``. Logs counts only, never a file
        name (a target name may be a customer's)."""
        destination = Path(destination)
        report = _delivery.deliver(list(items), destination, ini.id, on_conflict=on_conflict,
                                   make_zip=make_zip, cancel=cancel)
        try:
            self._workspace().remember_delivery_destination(ini, destination)
        except (OSError, ValueError) as exc:
            log.warning("Officina: destinazione della consegna non ricordata: %s", exc)
            report = dataclasses.replace(report, remember_problem=str(exc))
        log.info("Officina: consegna di %s: %d file, %d saltati, %d non riusciti%s%s",
                 ini.folder.name, len(report.delivered), len(report.skipped), len(report.failed),
                 ", zip" if report.zip_path else "", ", annullata" if report.cancelled else "")
        return report

    def last_delivery_destination(self, ini: Initiative) -> Path | None:
        return self._workspace().last_delivery_destination(ini)


# ------------------------------------------------------------------ helpers ---

def _enabled_generator(settings: OfficinaSettings, name: str) -> tuple[Any, str]:
    """``(endpoint, "")`` or ``(None, reason)``: ``name`` must be an enabled,
    non-PROD generator with a usable URL."""
    name = (name or "").strip()
    if not name:
        return None, "nessun generatore scelto per il caso"
    matches = [g for g in settings.generators if g.name == name] or \
              [g for g in settings.generators if g.name.casefold() == name.casefold()]
    if not matches:
        return None, f"il generatore '{name}' non è configurato in Impostazioni"
    endpoint = matches[0]
    if not endpoint.enabled:
        return None, f"il generatore '{endpoint.name}' non è attivo"
    if is_prod_like(endpoint.name):
        return None, f"il generatore '{endpoint.name}' sembra la produzione (prod): invio rifiutato"
    problem = generator_url_problem(endpoint.url, allow_loopback_http=True)
    if problem:
        return None, f"il generatore '{endpoint.name}': {problem}; invio rifiutato"
    return endpoint, ""


def _expected_type(case: Case, kind: str) -> tuple[str | None, str]:
    """``(type, where it comes from)``: the TARGET's type, else the AS-IS's.
    A new AS-IS is never held to the old AS-IS's type: a wrong AS-IS could
    otherwise never be replaced."""
    slots = (("target", case.target()),) if kind == "asis" else (
        ("target", case.target()), ("asis", case.asis()))
    for source, version in slots:
        if version is not None and version.doc_type in ("pdf", "html"):
            return version.doc_type, source
    return None, ""


def _type_mismatch(got: str | None, expected: str | None, source: str) -> str:
    if expected is None or got == expected:
        return ""
    reason = REASON_HTML_FOR_PDF if got == "html" else REASON_PDF_FOR_HTML
    if source == "asis":
        reason += (f" (atteso {expected.upper()} come l'AS-IS; "
                   "se l'AS-IS è sbagliato rigeneralo con una nota)")
    return reason


def _json_object(raw: bytes, *, what: str) -> dict:
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError):
        raise ValueError(f"{what} non è un JSON valido") from None
    if not isinstance(data, dict):
        raise ValueError(f"{what} non è un oggetto JSON (serve {{...}})")
    return data
