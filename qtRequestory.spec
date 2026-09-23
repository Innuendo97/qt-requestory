# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller recipe for qtRequestory.exe — one windowed file, no installer.

Build it through ``scripts/build.ps1`` (it gates on pytest and smoke-tests the
result); ``pyinstaller qtRequestory.spec`` from the repo venv works too.

Why the shape it has:

* **onefile** — the colleagues receive the exe over chat or a share and run it
  from wherever it lands. A folder-with-DLLs build gets separated from its
  folder sooner or later and then nothing starts.
* **console=False** — double-clicking must not flash a console, and the
  scheduled ``--sync`` run every hour must stay invisible. The price is that
  ``sys.stdout``/``sys.stderr`` can be ``None``; ``cli._guard_std_streams``
  handles that on the first line of ``main``.
* **upx=False** — UPX-packed exes are a reliable way to get quarantined by
  corporate AV. A few MB are not worth a support call.

The package is NOT pip-installed in the build venv (pytest runs with
``pythonpath=src``), so ``pathex`` points at ``src`` and the icons are listed as
explicit ``datas`` instead of being collected from installed package metadata.
"""
import os
import sys
from pathlib import Path

SPEC_DIR = Path(SPECPATH).resolve()
SRC = SPEC_DIR / "src"
SCRIPTS = SPEC_DIR / "scripts"
ICON_DIR = SRC / "qtrequestory" / "ui" / "icons"

# `scripts` for the version-resource generator below, `src` because
# collect_submodules has to be able to import the package it walks. The package
# is not pip-installed in the build venv (pytest runs with pythonpath=src), so
# nothing else would put it on the path.
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(SRC))
from PyInstaller.utils.hooks import collect_submodules  # noqa: E402
from make_version_info import write_version_info  # noqa: E402

# The Windows version resource is generated from qtrequestory.__version__ so the
# number is never written down twice; build.ps1 does it too, this keeps a bare
# `pyinstaller qtRequestory.spec` working.
VERSION_FILE = write_version_info()

# The four pages are reached through
# `importlib.import_module(f"{PAGES_PACKAGE}.{module}")` in ui/main_window.py
# (a lazy factory, so the shell can run before a page exists). A computed module
# name is invisible to PyInstaller's static analysis, so without this the whole
# `qtrequestory.ui.pages` package is left out — and because MainWindow._build_page
# swallows the ModuleNotFoundError by design, the exe starts, draws the rail, and
# shows "La pagina «Ricerca» non è disponibile in questa versione." on every page.
# Observed exactly like that on the first build; app.log said
# "pagina search non disponibile (No module named 'qtrequestory.ui.pages')".
# collect_submodules (not --collect-all) so a page added later is picked up too.
PAGE_MODULES = collect_submodules("qtrequestory.ui.pages")

# The four modules ui/main_window.py's PAGES actually asks import_module for. A
# collect_submodules that silently returned only the package (a moved directory,
# a renamed package) would otherwise build the exact broken exe this is here to
# prevent, and nothing would say so until someone opened the window.
for _page in ("search_page", "sync_page", "settings_page", "about_page"):
    assert f"qtrequestory.ui.pages.{_page}" in PAGE_MODULES, (
        f"qtrequestory.ui.pages.{_page} was not collected; got {PAGE_MODULES}"
    )

# ui/icons.py reads these from disk at runtime (ICON_DIR = Path(__file__).with_name("icons")),
# which under onefile resolves inside the extraction dir — hence the same relative
# path here. Without them the navigation rail renders with no icons at all and
# nothing crashes, which is why tests/test_packaging.py guards the wheel side too.
# app.ico is both the exe's icon resource (see `icon=` below) and bundled: at
# runtime icons.app_icon() loads every size from it (the hand-tuned 16 px one
# included) for the window icon, which is what the taskbar shows while the app
# runs. Without it app_icon() falls back to rendering app.svg.
datas = [
    (str(ICON_DIR / "*.svg"), "qtrequestory/ui/icons"),
    (str(ICON_DIR / "app.ico"), "qtrequestory/ui/icons"),
    (str(ICON_DIR / "LICENSE.md"), "qtrequestory/ui/icons"),
]

# Every exclusion below was verified against the built exe (GUI launch + the
# headless paths), not assumed. Note what is NOT here:
#   - PySide6.QtNetwork  -> ui/app.py builds the single-instance guard out of
#     QLocalServer/QLocalSocket. Excluding it makes the GUI die at import with
#     "ModuleNotFoundError: No module named 'PySide6.QtNetwork'".
#   - PySide6.QtSvg      -> not imported by our code, but Qt6Svg.dll backs the
#     `imageformats/qsvg.dll` plugin that renders every icon. Leave it alone.
excludes = [
    # --- stdlib we never import ------------------------------------------------
    "tkinter",   # pulls tcl/tk (~10 MB of runtime files) for a Qt application
    "unittest",  # test-only; reachable from doctest/pydoc, not from the app
    "pydoc",     # only the interactive `help()` needs it
    "doctest",
    # --- Qt modules the application never imports ------------------------------
    # src/ imports exactly QtCore, QtGui, QtWidgets and QtNetwork. These are all
    # present in PySide6-Essentials, so without the exclusions an accidental
    # import (or a hook that follows one) would quietly add tens of MB.
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuickControls2",
    "PySide6.QtQuickWidgets",
    "PySide6.QtQuickTest",
    "PySide6.QtDBus",   # Linux IPC; dead weight on Windows
    "PySide6.QtOpenGL",
    "PySide6.QtOpenGLWidgets",  # pairs with QtOpenGL; the UI is all raster
    "PySide6.QtDesigner",
    "PySide6.QtUiTools",  # the UI is hand-written Python, no .ui files
    "PySide6.QtHelp",
    "PySide6.QtTest",
    "PySide6.QtSql",  # the index is plain sqlite3 from the stdlib, in core/
    # Not shipped by PySide6-Essentials today. Listed so that the day someone
    # pip-installs the full `PySide6` wheel into the build venv, the exe does
    # not silently grow by a couple hundred MB of WebEngine and Qt3D.
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebChannel",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DRender",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DExtras",
]

a = Analysis(
    [str(SCRIPTS / "entrypoint.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=datas,
    # The only hidden imports are the dynamically loaded pages (see above).
    # Everything else is reached statically: cli.py imports the core eagerly and
    # the UI lazily but by name (`from qtrequestory.ui.app import run_gui`), and
    # an import inside a function is still visible to the module graph.
    hiddenimports=PAGE_MODULES,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)

# --- two binaries the Qt hooks collect that this application cannot use ------
#
# Excluding a Python module (above) does not help here: both come in as plain
# DLL dependencies, so they have to be filtered out of the analysis result.
# Measured on this build: dropping them took the exe from 39.81 MB to 30.18 MB
# (31 644 271 bytes; ~27 MB of uncompressed payload). Both removals were verified
# by launching the built GUI, not assumed.
#
# 1. opengl32sw.dll (19.7 MB uncompressed) — Qt's software OpenGL renderer, loaded only when
#    something asks for an OpenGL surface. This UI is QtWidgets on the raster
#    engine (QtOpenGL/QtQuick are excluded above), so nothing ever does; if a
#    future version draws with OpenGL, delete this filter first. It is also the
#    first thing to try if anyone ever reports a blank or black window (a VDI/RDP
#    session, a blacklisted GPU driver, QT_OPENGL=software in the environment).
# 2. libssl-3-*/libcrypto-3-* that do NOT come from the Python installation
#    (7.7 MB uncompressed) — PyInstaller's QtNetwork hook hunts for an OpenSSL build on the
#    build machine's PATH and ships whatever it finds, which on this machine
#    was an unrelated third-party product's copy. QtNetwork is used for exactly
#    one thing here, the QLocalServer single-instance guard (ui/app.py), which
#    is a named pipe and knows nothing about TLS. Shipping a stranger's crypto
#    DLLs also made the build non-reproducible from machine to machine.
#    Python's own libssl/libcrypto STAY: urllib does the real HTTPS downloads
#    in core/http.py through _ssl.pyd, which links them.
PYTHON_DLLS = Path(sys.base_prefix) / "DLLs"
DROP_BINARIES = {"opengl32sw.dll"}
OPENSSL_PREFIXES = ("libssl-", "libcrypto-")


def _keep_binary(entry) -> bool:
    dest, source = entry[0], entry[1]
    name = Path(dest).name.lower()
    if name in DROP_BINARIES:
        return False
    if name.startswith(OPENSSL_PREFIXES):
        return os.path.normcase(str(Path(source).parent)) == os.path.normcase(str(PYTHON_DLLS))
    return True


a.binaries = [entry for entry in a.binaries if _keep_binary(entry)]

# The filter above must never take Python's OpenSSL with it: without them
# `import ssl` fails and every https download in core/http.py dies at runtime,
# in a windowed exe that cannot even print the traceback.
_remaining = {Path(entry[0]).name.lower() for entry in a.binaries}
assert any(n.startswith("libssl-") for n in _remaining), "dropped Python's libssl"
assert any(n.startswith("libcrypto-") for n in _remaining), "dropped Python's libcrypto"

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="qtRequestory",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # see module docstring: AV false positives
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ICON_DIR / "app.ico"),
    version=str(VERSION_FILE),
)
