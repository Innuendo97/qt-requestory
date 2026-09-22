"""Fill ``scripts/version_info.txt.in`` with ``qtrequestory.__version__``.

The Windows version resource must not repeat the version number: a hand-edited
resource drifts, and then the Properties > Details tab of the exe disagrees
with what ``--version`` prints. So the number lives in exactly one place
(``src/qtrequestory/__init__.py``) and this script stamps it into the template.

``scripts/build.ps1`` runs it before PyInstaller; ``qtRequestory.spec`` runs it
too, so that a bare ``pyinstaller qtRequestory.spec`` also works. The generated
``scripts/version_info.txt`` is a build artefact and is not committed.

    .venv\\Scripts\\python.exe scripts\\make_version_info.py [OUTPUT]
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = Path(__file__).with_name("version_info.txt.in")
DEFAULT_OUTPUT = Path(__file__).with_name("version_info.txt")


def package_version() -> str:
    """``__version__`` from the source tree, whether or not the package is installed."""
    src = str(ROOT / "src")
    if src not in sys.path:
        sys.path.insert(0, src)
    from qtrequestory import __version__

    return __version__


def render(version: str) -> str:
    """The template with the version placeholders replaced.

    ``FixedFileInfo`` wants four integers, so a version has to be exactly
    ``MAJOR.MINOR.PATCH``; anything else (a ``1.0.0rc1``) would silently become
    a resource Windows refuses, so it is rejected here instead.
    """
    parts = version.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise ValueError(f"__version__ must be MAJOR.MINOR.PATCH, got {version!r}")
    major, minor, patch = parts
    text = TEMPLATE.read_text(encoding="utf-8")
    for placeholder, value in (("@MAJOR@", major), ("@MINOR@", minor),
                               ("@PATCH@", patch), ("@VERSION@", version)):
        text = text.replace(placeholder, value)
    return text


def write_version_info(output: Path | None = None) -> Path:
    """Write the resource file and return its path."""
    target = Path(output) if output is not None else DEFAULT_OUTPUT
    target.parent.mkdir(parents=True, exist_ok=True)
    # newline="\n": PyInstaller does not care, but a file that flips between
    # CRLF and LF depending on who built it makes every diff noisy.
    target.write_text(render(package_version()), encoding="utf-8", newline="\n")
    return target


def main() -> int:
    output = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    path = write_version_info(output)
    print(f"{path} (version {package_version()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
