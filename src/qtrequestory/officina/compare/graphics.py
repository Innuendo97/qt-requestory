"""The graphics of an extracted PDF page: paths and images (spec §3.1).

Pure data, filled by ``qtrequestory.officina.pdf`` (the reader) and consumed
by the extraction, its cache and the zones stage. It lives here, not in the
``pdf`` package, so that the cache and the zones never load pypdfium2.

Stdlib only; no Qt, no pypdfium2.
"""
from __future__ import annotations

from dataclasses import dataclass

__all__ = ["Box", "PageGraphics", "PathShape", "Rgba"]

Box = tuple[float, float, float, float]
Rgba = tuple[int, int, int, int]


@dataclass(frozen=True)
class PathShape:
    """One vector path of a page. ``box``: its bounds on the displayed page
    (points, top-left origin, like word boxes); ``stroke_width`` in points;
    ``fill`` / ``stroke``: RGBA 0-255, ``None`` when the path is not filled /
    not stroked; ``segments``: how many segments it has (a divider has 1-5, a
    logo or outlined text hundreds)."""

    box: Box
    stroke_width: float
    fill: Rgba | None
    stroke: Rgba | None
    segments: int


@dataclass(frozen=True)
class PageGraphics:
    """The graphics of one page: paths and image boxes (same space as words),
    in the page's drawing order, form XObjects included, those of hidden
    optional-content layers left out."""

    paths: tuple[PathShape, ...] = ()
    images: tuple[Box, ...] = ()
