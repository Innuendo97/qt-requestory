# Third-party notices

qtRequestory itself is MIT-licensed (`LICENSE` at the root of the repository).
The Windows executable also bundles the third-party components below. This file
travels with the executable (`qtrequestory/THIRD-PARTY-NOTICES.md` inside the
bundle) and with the wheel.

## pypdfium2 and PDFium

Used by the Officina tab to read, compare and draw PDF documents
(`qtrequestory/officina/pdf.py` is the only module that imports it).

- **pypdfium2** (https://github.com/pypdfium2-team/pypdfium2): the Python
  binding. Licence: `Apache-2.0 OR BSD-3-Clause`, at the user's choice.
- **PDFium** (https://pdfium.googlesource.com/pdfium/): the PDF engine, shipped
  as `pdfium.dll` inside `pypdfium2_raw` (binary build by the pdfium-binaries
  project). Licence: `(Apache-2.0 OR BSD-3-Clause) AND LicenseRef-PdfiumThirdParty`.
  `LicenseRef-PdfiumThirdParty` collects the licences of the libraries compiled
  into PDFium: libpng, LibTIFF, Anti-Grain Geometry 2.3, FreeType, Little CMS,
  OpenJPEG, zlib, libjpeg-turbo (with the IJG notice) and ICU.

The full texts ship unchanged in the package's metadata folder, which the build
bundles (`collect_all("pypdfium2")` in `qtRequestory.spec`):
`pypdfium2-<version>.dist-info/` holds `Apache-2.0.txt`, `BSD-3-Clause.txt`,
`LicenseRef-PdfiumThirdParty.txt` and `CC-BY-4.0.txt` (pypdfium2's
documentation), plus the `dep5-wheel` file that maps each file to its licence.

## Qt for Python (PySide6) and Qt

The user interface is built with **PySide6-Essentials** (https://doc.qt.io/qtforpython/)
and the Qt libraries it ships (`Qt6Core`, `Qt6Gui`, `Qt6Widgets`, `Qt6Network`,
`Qt6Svg`). They are used under the **GNU Lesser General Public License v3
(LGPL-3.0)**. The Qt libraries are separate dynamic libraries (DLLs) inside the
bundle and are not modified. Their source code is available from
https://download.qt.io/ and https://code.qt.io/; the LGPL-3.0 text is at
https://www.gnu.org/licenses/lgpl-3.0.html.

## Fluent UI System Icons

The toolbar and navigation icons come from Microsoft's Fluent UI System Icons
(MIT). The attribution and the licence text are in `ui/icons/LICENSE.md`,
bundled next to the icons.

## Python

The executable embeds the CPython 3.12 runtime (Python Software Foundation
License, https://docs.python.org/3/license.html) and the OpenSSL libraries that
ship with it (Apache-2.0).
