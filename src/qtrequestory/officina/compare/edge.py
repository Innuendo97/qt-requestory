"""HTML -> PDF with the Microsoft Edge installed on Windows (headless print).

An HTML case (an email body) is compared as text through its PDF print. Edge is
driven offline and deterministically:

* :func:`~qtrequestory.officina.compare.sanitise.sanitise_html` (an
  allow-list: only relative, ``data:`` and ``#`` references survive; scripts
  and event handlers go) writes a *sanitised copy* next to the output, and
  Edge renders that copy, never the original;
* the copy carries a Content-Security-Policy that blocks every fetch except
  ``data:`` images/fonts and inline styles, and switches JavaScript off (the
  ``--blink-settings=scriptEnabled=false`` switch makes --print-to-pdf write
  nothing, verified on Edge 2026-09);
* second layer: Edge runs with a throw-away profile, a dead proxy and a
  resolver that resolves nothing, so an HTTP reference that got past both the
  sanitiser and the policy still cannot load (the proxy does not cover
  SMB/UNC — the sanitiser and the policy do);
* throw-away profiles older than a day (left by a crash) are swept away;
* the exit code is not trusted: a known regression makes ``--headless=new``
  exit 0 without writing a valid PDF, so the output must start with ``%PDF-``
  and exceed 1 KB, and one retry runs with ``--headless=old``.

Stdlib only; no Qt, no pypdfium2.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from qtrequestory.officina.compare.sanitise import sanitise_html

__all__ = ["find_edge", "html_to_pdf", "sanitise_html"]

#: Prefix of the throw-away Edge profiles in the temp folder.
PROFILE_PREFIX = "qtr-edge-"
#: A leftover profile older than this is swept away (Edge killed, app crashed).
STALE_PROFILE_S = 24 * 3600
#: A valid print is at least this big (an empty page is still several KB).
MIN_PDF_BYTES = 1024
_EDGE_SUBPATH = Path("Microsoft") / "Edge" / "Application" / "msedge.exe"
_APP_PATHS = r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\msedge.exe"

# ------------------------------------------------------------------ Edge ---

def find_edge() -> Path | None:
    """``msedge.exe`` from the standard install folders or the App Paths key."""
    roots = [os.environ.get(v) for v in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")]
    for root in roots:
        if root and (candidate := Path(root) / _EDGE_SUBPATH).is_file():
            return candidate
    if sys.platform == "win32":
        import winreg

        for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(hive, _APP_PATHS) as key:
                    value, _ = winreg.QueryValueEx(key, None)
            except OSError:
                continue
            if value and (candidate := Path(str(value).strip('"'))).is_file():
                return candidate
        return None
    found = shutil.which("microsoft-edge") or shutil.which("msedge")
    return Path(found) if found else None


def html_to_pdf(html_path: Path, out_pdf: Path, *, timeout_s: int = 60,
                edge: Path | None = None) -> str | None:
    """Print ``html_path`` to ``out_pdf`` with Edge. ``None`` on success, else
    the reason (Italian, for the user).

    A sanitised copy ``<out stem>.sanitised.html`` is written next to
    ``out_pdf`` and rendered instead of the original. On failure ``out_pdf``
    does not exist (a stale or invalid file is removed).
    """
    exe = edge or find_edge()
    if exe is None:
        return "Microsoft Edge non trovato: impossibile convertire l'HTML in PDF"
    html_path, out_pdf = Path(html_path), Path(out_pdf)
    try:
        sanitised = out_pdf.with_name(out_pdf.stem + ".sanitised.html")
        sanitised.write_bytes(sanitise_html(html_path.read_bytes()))
    except OSError as exc:
        return f"impossibile preparare la copia dell'HTML: {exc}"
    _sweep_stale_profiles()
    errors: list[str] = []
    for mode in ("new", "old"):
        try:
            _remove(out_pdf)  # a stale file must never pass the check below
        except OSError as exc:
            return f"impossibile sostituire {out_pdf.name}: {exc}"
        with tempfile.TemporaryDirectory(prefix=PROFILE_PREFIX, ignore_cleanup_errors=True) as profile:
            failure = _run(_argv(exe, mode, Path(profile), out_pdf, sanitised), timeout_s)
        failure = failure or _invalid_output(out_pdf)
        if failure is None:
            return None
        errors.append(f"--headless={mode}: {failure}")
    try:
        _remove(out_pdf)
    except OSError:
        pass
    return "Edge non ha prodotto un PDF valido (" + "; ".join(errors) + ")"


def _sweep_stale_profiles(now: float | None = None) -> None:
    """Best effort: delete ``qtr-edge-*`` profiles in the temp folder older than a day."""
    now = time.time() if now is None else now
    try:
        entries = list(Path(tempfile.gettempdir()).glob(PROFILE_PREFIX + "*"))
    except OSError:
        return
    for entry in entries:
        try:
            if entry.is_dir() and now - entry.stat().st_mtime > STALE_PROFILE_S:
                shutil.rmtree(entry, ignore_errors=True)
        except OSError:
            continue


def _argv(exe: Path, mode: str, profile: Path, out_pdf: Path, page: Path) -> list[str]:
    return [
        str(exe),
        f"--headless={mode}",
        "--disable-gpu",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        "--disable-sync",
        "--disable-background-networking",
        "--disable-component-update",
        # Nothing may go online, even a reference the sanitiser missed.
        "--proxy-server=http://127.0.0.1:9",
        "--host-resolver-rules=MAP * ~NOTFOUND",
        "--no-pdf-header-footer",
        "--print-to-pdf-no-header",
        f"--print-to-pdf={out_pdf}",
        page.resolve().as_uri(),
    ]


def _run(argv: list[str], timeout_s: int) -> str | None:
    """Run Edge; ``None`` if it exited 0, else the reason."""
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, creationflags=flags)
    except OSError as exc:
        return f"impossibile avviare Edge: {exc}"
    try:
        code = proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        return f"Edge non ha risposto entro {timeout_s} s"
    return None if code == 0 else f"Edge è uscito con codice {code}"


def _kill_tree(proc: subprocess.Popen) -> None:
    """Stop Edge and the child processes it spawned (only our own tree)."""
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), check=False)
    proc.kill()
    proc.wait()


def _invalid_output(out_pdf: Path) -> str | None:
    try:
        size = out_pdf.stat().st_size
        with out_pdf.open("rb") as fh:
            head = fh.read(5)
    except OSError:
        return "nessun PDF scritto"
    if head != b"%PDF-":
        return "il file scritto non è un PDF"
    if size <= MIN_PDF_BYTES:
        return f"PDF troppo piccolo ({size} byte)"
    return None


def _remove(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass
