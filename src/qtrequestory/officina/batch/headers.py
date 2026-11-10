"""The header table of a Genera run (spec "Header").

The table IS the set of headers sent: it starts with the automatic names at
an empty value ("automatico") followed by the Impostazioni profile, and the
user may change a value, add a row or delete one (automatic rows included).

Unlike ``generator.resolve_headers`` (the Officina cases), there are no
layers here and no toggle: a deleted row is simply not sent, an empty value
on an automatic name is computed, an empty value on any other name is sent
empty. Names compare case-insensitively (HTTP does); the last row wins.

Stdlib + core only, Qt-free.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable

from qtrequestory.core.config import OfficinaSettings, header_name_problem, header_value_problem
from qtrequestory.officina.generator import POSTMAN_TOKEN, HeaderError

AUTOMATIC = ("template_key", "current_timestamp", "correlation_id", POSTMAN_TOKEN)

_AUTOMATIC_FOLDED = frozenset(name.casefold() for name in AUTOMATIC)


def default_rows(settings: OfficinaSettings) -> list[tuple[str, str]]:
    """The automatic rows at ``""``, then the profile of ``settings``.

    A profile entry named like an automatic row (case-insensitively) replaces
    that row in place: the profile wins.
    """
    rows: list[tuple[str, str]] = [(name, "") for name in AUTOMATIC]
    position = {name.casefold(): i for i, name in enumerate(AUTOMATIC)}
    for name, value in settings.header_profile.items():
        name = str(name).strip()
        if not name:
            continue
        row = (name, "" if value is None else str(value))
        folded = name.casefold()
        if folded in position:
            rows[position[folded]] = row
        else:
            position[folded] = len(rows)
            rows.append(row)
    return rows


def build_headers(
    rows: Iterable[tuple[str, str]],
    *,
    key: str,
    now_ms: int,
    new_uuid: Callable[[], str],
    postman_token: str,
) -> dict[str, str]:
    """The headers of one call from the table ``rows``.

    - a row without a name is ignored; names and values are stripped;
    - a name repeated (case-insensitively) keeps its last row, spelling included;
    - an automatic name with an empty value is computed: ``template_key`` =
      ``key``, ``current_timestamp`` = ``now_ms``, ``correlation_id`` =
      ``new_uuid()`` (called only then), ``Postman-Token`` = ``postman_token``
      (or the built-in default when that is blank);
    - any other name with an empty value is sent empty.

    Raises :class:`~qtrequestory.officina.generator.HeaderError` with the text
    of ``header_name_problem`` / ``header_value_problem`` for a malformed row.
    """
    merged: dict[str, tuple[str, str]] = {}  # folded name -> (name, value)
    for name, value in rows:
        name = str(name).strip()
        if not name:
            continue
        merged[name.casefold()] = (name, "" if value is None else str(value).strip())

    headers: dict[str, str] = {}
    for folded, (name, value) in merged.items():
        if not value and folded in _AUTOMATIC_FOLDED:
            value = _computed(folded, key=key, now_ms=now_ms, new_uuid=new_uuid,
                              postman_token=postman_token)
        problem = header_name_problem(name) or header_value_problem(name, value)
        if problem:
            raise HeaderError(f"intestazioni: {problem}")
        headers[name] = value
    return headers


def _computed(folded: str, *, key: str, now_ms: int, new_uuid: Callable[[], str],
              postman_token: str) -> str:
    if folded == "template_key":
        return key.strip()
    if folded == "current_timestamp":
        return str(int(now_ms))
    if folded == "correlation_id":
        return str(new_uuid())
    return postman_token.strip() or OfficinaSettings().postman_token
