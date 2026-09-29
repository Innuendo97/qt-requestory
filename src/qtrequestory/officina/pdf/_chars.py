"""Characters of a page for the ``pdf`` package: :class:`PageChars`, fonts,
and the reading of one page (after the ink tests).

Private to ``qtrequestory.officina.pdf`` (which re-exports the public names);
every caller holds its lock.
"""
from __future__ import annotations

import ctypes
import math
import re
from dataclasses import dataclass, field

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

from qtrequestory.officina.compare.graphics import PageGraphics
from qtrequestory.officina.pdf._geometry import Box, display_transform, snap
from qtrequestory.officina.pdf._ink import PAINTLESS, hidden_layer_graphics, hide_invisible_text
from qtrequestory.officina.pdf._objects import Reader, graphics


@dataclass(frozen=True)
class PageChars:
    """The raw text layer of one page, for ``compare.extract_pdf``.

    ``width``/``height`` are the page as DISPLAYED (after its CropBox and
    /Rotate). ``chars`` holds ``(text, text_box, display_box)`` per character
    in PDFium's order; a box is ``(x0, y0, x1, y1)``:

    * ``display_box``: points of the displayed page, origin at its TOP-left —
      where a viewer shows the glyph;
    * ``text_box``: unrotated user space with y pointing down — the text's own
      direction, for grouping characters into words and lines even on a
      rotated page.

    Whitespace and characters PDFium generated (implicit spaces, line breaks)
    come with ``None`` boxes: they only separate words. PDFium reports
    a hyphen at a line end as U+0002; it is returned as ``"-"``. A glyph with
    no Unicode mapping becomes U+FFFD, so its word stays whole.

    ``fonts`` runs parallel to ``chars``: ``(size in points, bold)`` for a
    character that may open a word — the first of the page and every one
    after a separator — and for every ROTATED character, ``None`` elsewhere
    (sampling every glyph would cost ~30% of the extraction). The size is the
    one DISPLAYED (the font size times the text matrix and CTM scale); bold
    comes from :func:`is_bold`. Empty when nothing was sampled.

    Phase 2.5, also parallel to ``chars`` (empty = the default for every
    character, as for a page read by an older extractor):

    * ``angles``: the glyph's angle in whole degrees, clockwise as PDFium
      reports it (``FPDFText_GetCharAngle``; 270 reads bottom-up), snapped to
      a multiple of 90 within 2 degrees; 0 for horizontal text and separators;
    * ``origins``: for a ROTATED character only, its origin on the baseline
      (``FPDFText_GetCharOrigin``) in text space; ``None`` elsewhere. Its
      ``text_box`` is then the TIGHT glyph box (``FPDFText_GetCharBox``) and
      its ``display_box`` the tight box displayed: the loose box of a rotated
      glyph has no area. A horizontal glyph whose loose box is empty is
      displayed with its tight box (its text box stays the loose one);
    * ``invisible``: the character paints nothing (render mode 3 or 7) — after
      the ink test (``_ink.hide_invisible_text``), which also puts text
      hidden by colour, transparency or an optional-content layer in mode 3.

    * ``fills``: the fill colour ``(r, g, b, a)`` of a character, sampled
      where ``fonts`` is (a word's first character, every rotated one),
      ``None`` elsewhere (review A2 I1: a watermark's pale colour).

    ``graphics`` is ``read_graphics`` of the page; ``image_count`` its
    number of images.
    """
    width: float
    height: float
    chars: list[tuple[str, Box | None, Box | None]]
    image_count: int
    fonts: list[tuple[float, bool] | None] = field(default_factory=list)
    angles: list[int] = field(default_factory=list)
    origins: list[tuple[float, float] | None] = field(default_factory=list)
    invisible: list[bool] = field(default_factory=list)
    graphics: PageGraphics = PageGraphics()
    fills: list[tuple[int, int, int, int] | None] = field(default_factory=list)


#: Font-name markers of a bold face (matched case-insensitively).
_BOLD_NAMES = ("bold", "black", "heavy")  # "bold" also covers "Semibold"
#: A font subset's tag: six capitals and a plus ("ABCDEF+Arial-BoldMT").
_SUBSET = re.compile(r"^[A-Z]{6}\+")


def font_name(raw: bytes) -> str:
    """A font's base name as PDFium returns it, without the subset tag."""
    return _SUBSET.sub("", raw.decode("latin-1").rstrip("\0"))


def is_bold(weight: int, name: str) -> bool:
    """Whether a font is bold: by its weight when PDFium knows it (≥ 600), and
    by its name either way ("Bold", "Black", "Heavy", "Semibold"): PDFium
    derives the weight from the stem width, which puts a real bold face well
    under 600 (Arial Bold reads 520)."""
    lowered = name.lower()
    return weight >= 600 or any(marker in lowered for marker in _BOLD_NAMES)


class _FontSampler:
    """Reads one character's font from a text page (buffers reused)."""

    def __init__(self, textpage_raw) -> None:
        self._raw = textpage_raw
        self._name = ctypes.create_string_buffer(256)
        self._flags = ctypes.c_int()
        self._matrix = pdfium_c.FS_MATRIX()
        self._rgba = tuple(ctypes.c_uint() for _ in range(4))

    def __call__(self, index: int) -> tuple[float, bool]:
        size = pdfium_c.FPDFText_GetFontSize(self._raw, index)
        if pdfium_c.FPDFText_GetMatrix(self._raw, index, ctypes.byref(self._matrix)):
            m = self._matrix
            size *= math.sqrt(abs(m.a * m.d - m.b * m.c))
        length = pdfium_c.FPDFText_GetFontInfo(self._raw, index, self._name, len(self._name),
                                               ctypes.byref(self._flags))
        name = font_name(self._name.raw[:length]) if 0 < length <= len(self._name) else ""
        weight = pdfium_c.FPDFText_GetFontWeight(self._raw, index)
        return round(size, 2), is_bold(weight, name)

    def fill(self, index: int) -> tuple[int, int, int, int] | None:
        """The character's fill colour (RGBA 0-255); None when PDFium has none."""
        r, g, b, a = self._rgba
        if not pdfium_c.FPDFText_GetFillColor(self._raw, index, r, g, b, a):
            return None
        return (r.value, g.value, b.value, a.value)


def page_chars(page: pdfium.PdfPage, layers: set[str] | None = None) -> PageChars:
    """One page's characters and graphics, after the ink tests.

    The text page is built with the page's /Rotate neutralised (in memory only;
    the document is never saved): on a page rotated 180°, PDFium's text page
    takes the upside-down text for right-to-left and returns it reversed and
    split. Glyph boxes are in user space either way; the REAL rotation is then
    applied to them by the display transform, computed before neutralising.
    ``layers``: the optional-content layers seen drawing on earlier pages of
    the same document (updated; see ``_ink.hidden_layer_graphics``).
    """
    textpage = None
    rotation = 0
    try:
        width, height = page.get_size()
        to_display = display_transform(page, width, height)
        reader = Reader()
        objects = reader.objects(page)
        rotation = page.get_rotation()
        if rotation:
            page.set_rotation(0)
        shapes = graphics(reader, objects, to_display, hidden_layer_graphics(page, reader, objects, layers))
        paintless = hide_invisible_text(page, reader, objects)
        textpage = page.get_textpage()
        raw = textpage.raw
        sample = _FontSampler(raw)
        chars: list[tuple[str, Box | None, Box | None]] = []
        fonts: list[tuple[float, bool] | None] = []
        angles: list[int] = []
        origins: list[tuple[float, float] | None] = []
        invisible: list[bool] = []
        fills: list[tuple[int, int, int, int] | None] = []
        ox, oy = ctypes.c_double(), ctypes.c_double()
        for i in range(textpage.count_chars()):
            code = pdfium_c.FPDFText_GetUnicode(raw, i)
            generated = pdfium_c.FPDFText_IsGenerated(raw, i) == 1
            if code == 2:
                ch = "-"
            elif 0 < code < 0x110000:
                ch = chr(code)
            else:
                ch = " " if generated else "�"
            if ch.isspace() or (generated and code != 2):
                chars.append((" ", None, None))
                fonts.append(None)
                angles.append(0)
                origins.append(None)
                invisible.append(False)
                fills.append(None)
                continue
            angle = snap(pdfium_c.FPDFText_GetCharAngle(raw, i))
            origin = None
            left, bottom, right, top = textpage.get_charbox(i, loose=True)
            shown = (left, bottom, right, top)
            if angle or right <= left or top <= bottom:
                shown = textpage.get_charbox(i)  # tight: a rotated glyph's loose box has no area
                if angle:
                    left, bottom, right, top = shown
                    pdfium_c.FPDFText_GetCharOrigin(raw, i, ox, oy)
                    origin = (ox.value, -oy.value)
            x_a, y_a = to_display(shown[0], shown[1])
            x_b, y_b = to_display(shown[2], shown[3])
            chars.append((
                ch,
                (left, -top, right, -bottom),
                (min(x_a, x_b), min(y_a, y_b), max(x_a, x_b), max(y_a, y_b)),
            ))
            opens_word = len(chars) == 1 or chars[-2][1] is None
            fonts.append(sample(i) if opens_word or angle else None)
            fills.append(sample.fill(i) if opens_word or angle else None)
            angles.append(angle)
            origins.append(origin)
            invisible.append(paintless and pdfium_c.FPDFText_GetTextRenderMode(raw, i) in PAINTLESS)
        rotated = any(angles)
        return PageChars(width, height, chars, len(shapes.images), fonts,
                         angles if rotated else [], origins if rotated else [],
                         invisible if any(invisible) else [], shapes, fills)
    finally:
        if textpage is not None:
            textpage.close()
        if rotation:
            page.set_rotation(rotation)  # leave the in-memory document as it was
        page.close()
