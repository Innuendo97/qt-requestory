"""The Genera presenter's read-only side: its state as properties, and what
the tab says about it — the button, the confirmation, the notes under the
fields and the header summary.

A mixin of :class:`~qtrequestory.ui.pages.genera_presenter.GeneraPresenter`
(it reads the presenter's state, changes nothing): the presenter keeps the
state and the rules, this module the views and the words.
"""
from __future__ import annotations

from pathlib import Path

from qtrequestory.ui import strings
from qtrequestory.ui.contracts import NO_PACKAGE, BatchRequest, Elenco
from qtrequestory.ui.pages.genera_headers import headers_summary, modified_count

__all__ = ["GeneraViews", "plural"]


def plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many.format(n=n)


class GeneraViews:
    """Reads the presenter's ``_*`` fields and ``call_count``/``keys``/``fdis``/``build_request``."""

    # -- state (read-only views) ------------------------------------------------

    @property
    def activated(self) -> bool:
        return self._activated

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def keys_text(self) -> str:
        return self._keys_text

    @property
    def fdi_text(self) -> str:
        return self._fdi_text

    @property
    def elenco(self) -> Elenco | None:
        return self._elenco

    @property
    def elenco_path(self) -> Path | None:
        return self._elenco_path

    @property
    def elenco_error(self) -> str:
        return self._elenco_error

    @property
    def checked_packages(self) -> frozenset[str]:
        return frozenset(self._checked)

    @property
    def generators(self) -> list[str]:
        return list(self._generators)

    @property
    def generator(self) -> str:
        return self._generator

    @property
    def envs(self) -> list[str]:
        return list(self._envs)

    @property
    def source_env(self) -> str:
        return self._source_env

    @property
    def destination(self) -> Path | None:
        return self._destination

    @property
    def header_rows(self) -> list[tuple[str, str]]:
        return list(self._headers)

    @property
    def make_zip(self) -> bool:
        return self._make_zip

    @property
    def save_html(self) -> bool:
        return self._save_html

    def has_generator(self) -> bool:
        return bool(self._generators)

    # -- wording -------------------------------------------------------------------

    def start_text(self) -> str:
        """The primary button: what pressing it will do."""
        n = self.call_count()
        if not n:
            return strings.GENERA_START
        if self._mode == "fdi":
            return plural(n, strings.GENERA_START_FDI_ONE, strings.GENERA_START_FDI)
        return plural(n, strings.GENERA_START_ONE, strings.GENERA_START_N)

    def confirmation(self, request: BatchRequest | None = None,
                     count: int | None = None) -> tuple[str, str]:
        """``(title, text)`` of the question over ``CONFIRM_ABOVE`` calls.
        ``count`` is the real number of calls (looked up first when the
        request has FDIs); ``None``: one call per target."""
        request = request or self.build_request()
        n = len(request.targets) if count is None else count
        env, source = request.generator, request.source_env
        fdis = sum(1 for t in request.targets if t.kind == "fdi")
        title = strings.GENERA_CONFIRM_TITLE.format(n=n)
        if fdis:
            return title, strings.GENERA_CONFIRM_TEXT_FDI.format(n=n, fdis=fdis, env=env, source=source)
        return title, strings.GENERA_CONFIRM_TEXT.format(n=n, env=env, source=source)

    def keys_note(self) -> str:
        """Under the keys field: how many, and where they will be written."""
        n = len(self.keys())
        if not n:
            return ""
        where = (strings.GENERA_KEYS_FOLDER_ELENCO.format(file=self._elenco_path.name)
                 if self._elenco is not None and self._elenco_path is not None
                 else strings.GENERA_KEYS_FOLDER_NONE.format(folder=NO_PACKAGE))
        return f"{strings.GENERA_KEYS_COUNT.format(n=n)}{strings.GENERA_SUM_SEPARATOR}{where}"

    def fdi_note(self) -> str:
        n = len(self.fdis())
        return strings.GENERA_FDI_COUNT.format(n=n) if n else ""

    def elenco_summary(self) -> str:
        if self._elenco is None:
            return ""
        total = len(self._elenco.packages())
        return strings.GENERA_ELENCO_SUMMARY.format(chosen=len(self._checked), total=total,
                                                    keys=len(self._elenco.keys_of(self._checked)))

    def elenco_skipped_note(self) -> str:
        skipped = self._elenco.skipped if self._elenco is not None else 0
        return plural(skipped, strings.GENERA_ELENCO_SKIPPED_ONE, strings.GENERA_ELENCO_SKIPPED) if skipped else ""

    def modified_headers(self) -> int:
        return modified_count(self._default_headers, self._headers)

    def headers_summary(self) -> str:
        return headers_summary(self._default_headers, self._headers)
