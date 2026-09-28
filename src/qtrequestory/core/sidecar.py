"""The Officina's generators carried by ``environments.json`` (release 1.3.2).

The sidecar next to the exe is how a colleague hands over the hostnames this
public repository never contains. Besides the log environments it may carry
the document generators, in the object form of
:func:`~qtrequestory.core.config.read_sidecar_json`::

    {"environments": [{"name": ..., "url": ...}],
     "generators":   [{"name": ..., "url": ..., "enabled": true}]}

The first-run wizard and the Officina's setup card offer them prefilled.
Nothing here writes anything: the user still confirms, and ``config.save``
stores what they confirmed.

The generators are held to the very rules Impostazioni applies
(``config.generator_problems``: https only, no ``prod`` anywhere, unique
names). A generator that breaks one is dropped with a log line — never a
crash, and never its URL in the log: it may carry a signature.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from qtrequestory.core.config import (
    GeneratorEndpoint,
    find_sidecar_environments,
    generator_problems,
    read_sidecar_json,
)

__all__ = ["import_generators_file", "sidecar_generators"]

log = logging.getLogger(__name__)


def import_generators_file(path: Path) -> list[GeneratorEndpoint]:
    """The valid generators of the sidecar at ``path``; ``[]`` when it has none.

    ValueError only when the file itself is unreadable (as for the
    environments); a bad *generator* is skipped with a warning.
    """
    raw = read_sidecar_json(path).get("generators")
    if raw is None:
        return []
    if not isinstance(raw, list):
        log.warning("%s: 'generators' ignorato: atteso un elenco", path.name)
        return []
    accepted: list[GeneratorEndpoint] = []
    for n, item in enumerate(raw, 1):
        generator, problem = _generator_from_item(item)
        if generator is not None:
            problems = generator_problems([*accepted, generator])[-1]
            problem = "; ".join(problems)
        if problem:
            log.warning("%s: generatore n. %d ignorato: %s", path.name, n, problem)
            continue
        accepted.append(generator)
    return accepted


def sidecar_generators(exe_dir: Path) -> list[GeneratorEndpoint]:
    """The generators of the ``environments.json`` next to the exe; ``[]``
    when there is no such file, or it cannot be read (logged, never raised)."""
    path = find_sidecar_environments(exe_dir)
    if path is None:
        return []
    try:
        return import_generators_file(path)
    except (OSError, ValueError) as exc:
        log.warning("generatori di %s non letti: %s", path.name, exc)
        return []


def _generator_from_item(item: Any) -> tuple[GeneratorEndpoint | None, str]:
    """The shape check (the rules come after): ``(generator, "")`` or ``(None, why)``."""
    if not isinstance(item, dict):
        return None, f"atteso un oggetto, trovato {type(item).__name__}"
    name, url, enabled = item.get("name"), item.get("url"), item.get("enabled", True)
    if not isinstance(name, str):
        return None, "campo 'name' mancante o non stringa"
    if not isinstance(url, str) or not url.strip():
        return None, "campo 'url' mancante o non stringa"
    if not isinstance(enabled, bool):
        return None, "campo 'enabled' deve essere true/false"
    return GeneratorEndpoint(name=name.strip(), url=url.strip(), enabled=enabled), ""
