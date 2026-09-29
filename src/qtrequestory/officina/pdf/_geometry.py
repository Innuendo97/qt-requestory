"""Coordinates for the ``pdf`` package: display transform, matrices, angles.

Private to ``qtrequestory.officina.pdf``; every caller holds its lock.
"""
from __future__ import annotations

import ctypes
import math

import pypdfium2 as pdfium
import pypdfium2.raw as pdfium_c

Box = tuple[float, float, float, float]
#: An affine matrix ``(a, b, c, d, e, f)`` in PDF's row-vector convention.
Matrix = tuple[float, float, float, float, float, float]

#: Device scale used to read PDFium's page-to-display transform exactly
#: (FPDF_PageToDevice returns whole device pixels).
_SCALE = 1000


def display_transform(page: pdfium.PdfPage, width: float, height: float):
    """PDF user space -> displayed page (points, top-left origin).

    Built from ``FPDF_PageToDevice``, so it applies the CropBox offset and the
    page's /Rotate exactly as a viewer does. Computed once: the returned
    function stays valid after the page's /Rotate is changed in memory.
    """
    dev_w, dev_h = round(width * _SCALE), round(height * _SCALE)

    def device(x: float, y: float) -> tuple[float, float]:
        dx, dy = ctypes.c_int(), ctypes.c_int()
        pdfium_c.FPDF_PageToDevice(page.raw, 0, 0, dev_w, dev_h, 0, x, y, dx, dy)
        return dx.value / _SCALE, dy.value / _SCALE

    ox, oy = device(0, 0)
    ax, ay = device(1000, 0)
    bx, by = device(0, 1000)
    a, b = (ax - ox) / 1000, (ay - oy) / 1000   # d(display)/dx
    c, d = (bx - ox) / 1000, (by - oy) / 1000   # d(display)/dy

    def apply(x: float, y: float) -> tuple[float, float]:
        return ox + a * x + c * y, oy + b * x + d * y

    return apply


def then(first: Matrix, second: Matrix) -> Matrix:
    """The matrix applying ``first``, then ``second``."""
    a1, b1, c1, d1, e1, f1 = first
    a2, b2, c2, d2, e2, f2 = second
    return (a1 * a2 + b1 * c2, a1 * b2 + b1 * d2, c1 * a2 + d1 * c2, c1 * b2 + d1 * d2,
            e1 * a2 + f1 * c2 + e2, e1 * b2 + f1 * d2 + f2)


def corners(box: Box, apply) -> Box:
    """The bounds of ``box`` (left, bottom, right, top) mapped point by point by ``apply``."""
    left, bottom, right, top = box
    points = [apply(x, y) for x in (left, right) for y in (bottom, top)]
    xs, ys = [x for x, _ in points], [y for _, y in points]
    return (min(xs), min(ys), max(xs), max(ys))


def union(boxes: list[Box]) -> Box:
    return (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))


def snap(radians: float) -> int:
    """PDFium's char angle (radians, clockwise; -1 on error) in whole degrees,
    snapped to a multiple of 90 within 2 degrees."""
    if radians < 0:
        return 0
    degrees = math.degrees(radians) % 360
    nearest = round(degrees / 90) * 90
    return int(nearest % 360) if abs(degrees - nearest) <= 2 else int(round(degrees)) % 360
