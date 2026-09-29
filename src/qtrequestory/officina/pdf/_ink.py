"""Ink tests for the ``pdf`` package (spec §3.1): what a reader can see.

A suspect object is rendered, made to paint nothing IN MEMORY (the document
is never saved), and rendered again: unchanged pixels mean nobody could see
it. Both functions run with the page's /Rotate neutralised (the renders are in
user space, cropped to the object's box).

Private to ``qtrequestory.officina.pdf``; every caller holds its lock.
"""
from __future__ import annotations

from collections import defaultdict

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

from qtrequestory.officina.pdf._geometry import Box, union
from qtrequestory.officina.pdf._objects import IMAGE, PATH, TEXT, PageObject, Reader

#: Text render modes that paint nothing: 3 = invisible, 7 = clip only.
PAINTLESS = frozenset({3, 7})
#: A fill at least this light (every channel) may be white on white: the ink test decides.
_LIGHT = 235
#: Pixels per point of the text ink test's renders.
_INK_SCALE = 2
#: Pixels per point of the layer test's renders (its area can be most of the
#: page; a layer that is OFF draws nothing at any scale).
_LAYER_SCALE = 0.75
#: How far (user space units) a graphic is moved to take it out of a render.
_AWAY = 1e5


def hide_invisible_text(page: pdfium.PdfPage, reader: Reader, objects: list[PageObject]) -> bool:
    """Every SUSPECT text object — in an optional-content layer (itself or an
    enclosing form), filled light (≥ :data:`_LIGHT`) or fully transparent —
    that paints no pixel is left in render mode 3, so its characters report it
    on the text page built afterwards. White text on a coloured background
    changes the pixels: it stays visible. Text drawn off the page needs no
    test: the extractor drops it by position.

    True when any text of the page now paints nothing (mode 3 or 7).
    """
    crop = page.get_cropbox()
    paintless = False
    for obj in objects:
        if obj[1] != TEXT:
            continue
        handle = obj[0]
        mode = pdfium_c.FPDFTextObj_GetTextRenderMode(handle)
        if mode in PAINTLESS:
            paintless = True
            continue
        fill = reader.colour(pdfium_c.FPDFPageObj_GetFillColor, handle)
        light = fill is not None and (min(fill[:3]) >= _LIGHT or fill[3] == 0)
        if not (light or obj[3] or reader.layer(handle)):
            continue
        box = reader.bounds(obj)
        if box is None:
            continue
        before = ink(page, box, crop)
        pdfium_c.FPDFTextObj_SetTextRenderMode(handle, 3)
        if ink(page, box, crop) == before:
            paintless = True
        else:
            pdfium_c.FPDFTextObj_SetTextRenderMode(handle, mode)
    return paintless


def hidden_layer_graphics(page: pdfium.PdfPage, reader: Reader, objects: list[PageObject],
                          visible: set[str] | None = None) -> set[int]:
    """The indices (in ``objects``) of the paths and images of optional-content
    layers that are OFF (review A1, M1): a hidden logo, divider or watermark
    must not reach the zones. One test per layer and page: all its graphics
    are moved off the page together (their matrices restored right after); a
    layer whose area renders the same without them draws nothing.

    ``visible``: layers already seen drawing, shared by the pages of one
    document (a layer's state is document-wide): they are not tested again.
    Only "drawing" is remembered — a layer that drew nothing on one page (its
    graphics covered, say) is tested again on the next."""
    layers: dict[str, list[int]] = defaultdict(list)
    for index, obj in enumerate(objects):
        if obj[1] in (PATH, IMAGE):
            layer = obj[3] or reader.layer(obj[0])
            if layer and not (visible and layer in visible):
                layers[layer].append(index)
    hidden: set[int] = set()
    if not layers:
        return hidden
    crop = page.get_cropbox()
    for layer, members in layers.items():
        boxes = [box for box in (reader.bounds(objects[i]) for i in members) if box is not None]
        if not boxes:
            continue
        area = union(boxes)
        before = ink(page, area, crop, _LAYER_SCALE)
        saved = [(objects[i][0], reader.matrix(objects[i][0])) for i in members]
        try:
            for handle, (a, b, c, d, e, f) in saved:
                pdfium_c.FPDFPageObj_SetMatrix(handle, pdfium_c.FS_MATRIX(a, b, c, d, e + _AWAY, f + _AWAY))
            unchanged = ink(page, area, crop, _LAYER_SCALE) == before
        finally:
            for handle, matrix in saved:
                pdfium_c.FPDFPageObj_SetMatrix(handle, pdfium_c.FS_MATRIX(*matrix))
        if unchanged:
            hidden.update(members)
        elif visible is not None:
            visible.add(layer)
    return hidden


def ink(page: pdfium.PdfPage, box: Box, crop: Box, scale: float = _INK_SCALE) -> bytes:
    """The pixels of ``box`` (user space, 1 pt of margin) on white; empty
    bytes when none of it is on the page."""
    left, bottom, right, top = box
    c_left, c_bottom, c_right, c_top = crop
    cut = (max(0.0, left - c_left - 1), max(0.0, bottom - c_bottom - 1),
           max(0.0, c_right - right - 1), max(0.0, c_top - top - 1))
    if cut[0] + cut[2] >= c_right - c_left - 0.5 or cut[1] + cut[3] >= c_top - c_bottom - 0.5:
        return b""
    bitmap = page.render(scale=scale, crop=cut, fill_color=(255, 255, 255, 255), draw_annots=False,
                         may_draw_forms=False, force_bitmap_format=pdfium_c.FPDFBitmap_BGRx)
    try:
        return bytes(bitmap.buffer)
    finally:
        bitmap.close()
