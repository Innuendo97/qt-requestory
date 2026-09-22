"""Where the application keeps its own files.

App data lives under ``%LOCALAPPDATA%\\qtRequestory`` (override with the
``QTREQUESTORY_HOME`` environment variable — used by tests and portable setups).
Never derive anything from ``argv[0]`` or the working directory: under Task
Scheduler both are unreliable.
"""
from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "qtRequestory"
HOME_ENV_VAR = "QTREQUESTORY_HOME"
OUTPUT_DIR_NAME = "qtrequestory-calls"


@dataclass(frozen=True)
class AppPaths:
    app_dir: Path

    @property
    def config_file(self) -> Path:
        return self.app_dir / "config.json"

    @property
    def logs_dir(self) -> Path:
        return self.app_dir / "logs"

    @property
    def app_log(self) -> Path:
        return self.logs_dir / "app.log"

    @property
    def sync_log(self) -> Path:
        return self.logs_dir / "sync.log"

    @property
    def ui_state_file(self) -> Path:
        return self.app_dir / "ui-state.json"

    def ensure(self) -> AppPaths:
        self.app_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        return self


def default_app_dir() -> Path:
    override = os.environ.get(HOME_ENV_VAR)
    if override:
        return Path(override)
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / APP_NAME


def app_paths() -> AppPaths:
    return AppPaths(default_app_dir())


def default_output_dir() -> Path:
    return Path(tempfile.gettempdir()) / OUTPUT_DIR_NAME


def default_mirror_root() -> Path:
    return Path.home() / APP_NAME / "logs"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def executable_path() -> Path | None:
    """Path of the packaged exe, or None when running from source."""
    return Path(sys.executable).resolve() if is_frozen() else None


def executable_dir() -> Path:
    """Folder to look for sidecar files (environments.json) in."""
    exe = executable_path()
    return exe.parent if exe else Path.cwd()
