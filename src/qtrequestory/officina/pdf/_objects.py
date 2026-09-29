"""Page objects for the ``pdf`` package: the walk into form XObjects, bounds,
colours, optional-content layers, and the page's graphics.

Private to ``qtrequestory.officina.pdf``; every caller holds its lock.
"""
from __future__ import annotations

import ctypes
import math

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

from qtrequestory.officina.compare.graphics import PageGraphics, PathShape
from qtrequestory.officina.pdf._geometry import Box, Matrix, corners, then

#: How deep form XObjects are followed (graphics and ink tests).
DEPTH = 4
TEXT, PATH, IMAGE, FORM = (pdfium_c.FPDF_PAGEOBJ_TEXT, pdfium_c.FPDF_PAGEOBJ_PATH,
                           pdfium_c.FPDF_PAGEOBJ_IMAGE, pdfium_c.FPDF_PAGEOBJ_FORM)
#: The layer key of optional content whose group has no readable /Name.
_UNNAMED = "OC"

#: A page object: raw handle, type, the matrix from its form to the page
#: (``None`` on the page itself), and the optional-content layer of an
#: enclosing form (its /Name; ``None`` outside any marked form).
PageObject = tuple[object, int, "Matrix | None", "str | None"]


class Reader:
    """Page-object queries with reused ctypes buffers (a page written by Qt
    has one text object per glyph: tens of thousands per document)."""

    def __init__(self) -> None:
        self._f = [ctypes.c_float() for _ in range(4)]
        self._u = [ctypes.c_uint() for _ in range(4)]
        self._modes = (ctypes.c_long(), ctypes.c_long())  # FPDFPath_GetDrawMode takes long*
        self._matrix = pdfium_c.FS_MATRIX()
        self._name = ctypes.create_string_buffer(16)
        self._value = ctypes.create_string_buffer(256)
        self._length = ctypes.c_ulong()

    def objects(self, page: pdfium.PdfPage) -> list[PageObject]:
        """Every object of ``page``, form XObjects followed to :data:`DEPTH`."""
        out: list[PageObject] = []

        def visit(count, get, matrix, layer, depth):
            for k in range(count):
                handle = get(k)
                kind = pdfium_c.FPDFPageObj_GetType(handle)
                out.append((handle, kind, matrix, layer))
                if kind == FORM and depth < DEPTH:
                    own = self.matrix(handle)
                    visit(pdfium_c.FPDFFormObj_CountObjects(handle),
                          lambda i, h=handle: pdfium_c.FPDFFormObj_GetObject(h, i),
                          own if matrix is None else then(own, matrix),
                          layer or self.layer(handle), depth + 1)

        raw = page.raw
        visit(pdfium_c.FPDFPage_CountObjects(raw), lambda i: pdfium_c.FPDFPage_GetObject(raw, i), None, None, 0)
        return out

    def matrix(self, handle) -> Matrix:
        m = self._matrix
        if not pdfium_c.FPDFPageObj_GetMatrix(handle, m):
            return (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
        return (m.a, m.b, m.c, m.d, m.e, m.f)

    def bounds(self, obj: PageObject) -> Box | None:
        """The object's bounds in PDF user space of the page (form matrices applied)."""
        left, bottom, right, top = self._f
        if not pdfium_c.FPDFPageObj_GetBounds(obj[0], left, bottom, right, top):
            return None
        box = (left.value, bottom.value, right.value, top.value)
        matrix = obj[2]
        if matrix is None:
            return box
        a, b, c, d, e, f = matrix
        return corners(box, lambda x, y: (a * x + c * y + e, b * x + d * y + f))

    def colour(self, getter, handle) -> tuple[int, int, int, int] | None:
        r, g, b, a = self._u
        if not getter(handle, r, g, b, a):
            return None
        return (r.value, g.value, b.value, a.value)

    def layer(self, handle) -> str | None:
        """The optional-content layer the object is marked with (``/OC … BDC``):
        its group's /Name, or ``"OC"`` without one; ``None`` if not marked."""
        for k in range(pdfium_c.FPDFPageObj_CountMarks(handle)):
            mark = pdfium_c.FPDFPageObj_GetMark(handle, k)
            if not (pdfium_c.FPDFPageObjMark_GetName(mark, self._name, len(self._name), ctypes.byref(self._length))
                    and self._length.value == 6 and self._name.raw[:4] == b"O\x00C\x00"):
                continue
            if (pdfium_c.FPDFPageObjMark_GetParamStringValue(mark, b"Name", self._value, len(self._value),
                                                             ctypes.byref(self._length))
                    and 2 < self._length.value <= len(self._value)):
                return self._value.raw[:self._length.value - 2].decode("utf-16-le", "replace") or _UNNAMED
            return _UNNAMED
        return None

    def path(self, obj: PageObject, box: Box) -> PathShape:
        handle = obj[0]
        fill_mode, stroked = self._modes
        if not pdfium_c.FPDFPath_GetDrawMode(handle, fill_mode, stroked):
            fill_mode.value = stroked.value = 0
        width = 0.0
        if stroked.value and pdfium_c.FPDFPageObj_GetStrokeWidth(handle, self._f[0]):
            m = self.matrix(handle) if obj[2] is None else then(self.matrix(handle), obj[2])
            width = round(self._f[0].value * math.sqrt(abs(m[0] * m[3] - m[1] * m[2])), 3)
        return PathShape(box, width,
                         self.colour(pdfium_c.FPDFPageObj_GetFillColor, handle) if fill_mode.value else None,
                         self.colour(pdfium_c.FPDFPageObj_GetStrokeColor, handle) if stroked.value else None,
                         max(0, pdfium_c.FPDFPath_CountSegments(handle)))


def graphics(reader: Reader, objects: list[PageObject], to_display, hidden: set[int]) -> PageGraphics:
    """The paths and image boxes among ``objects`` (displayed with
    ``to_display``), without the objects whose index is in ``hidden``."""
    paths: list[PathShape] = []
    images: list[Box] = []
    for index, obj in enumerate(objects):
        if obj[1] not in (PATH, IMAGE) or index in hidden:
            continue
        box = reader.bounds(obj)
        if box is None:
            continue
        shown = corners(box, to_display)
        if obj[1] == IMAGE:
            images.append(shown)
        else:
            paths.append(reader.path(obj, shown))
    return PageGraphics(tuple(paths), tuple(images))
