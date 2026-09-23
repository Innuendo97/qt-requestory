"""Screenshots of the first-run wizard, for looking at UI changes (dev only).

    python scripts/dev/shoot_wizard.py [--modes light dark] [--out DIR] [--platform windows]

Same safety as ``shoot.py`` (whose isolation it reuses): the fake core — so the
scheduler is ``FakeSchedulerApi`` and no scheduled task is ever queried or
touched — a temp home, INI ``QSettings`` in a temp folder, and a wizard that is
never shown on screen. PNGs are named ``<mode>-wizard-<nn>-<what>.png``.
"""
from __future__ import annotations

import argparse
import dataclasses
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from shoot import _isolate  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--modes", nargs="+", default=["light", "dark"],
                        choices=["light", "dark", "system"])
    parser.add_argument("--out", type=Path, default=Path(tempfile.gettempdir()) / "qtr-shots")
    parser.add_argument("--platform", default="windows",
                        help="Qt platform plugin; 'offscreen' has no real fonts")
    args = parser.parse_args(argv)

    tmp = Path(tempfile.mkdtemp(prefix="qtr-shoot-wizard-"))
    _isolate(tmp)
    os.environ["QT_QPA_PLATFORM"] = args.platform
    args.out.mkdir(parents=True, exist_ok=True)

    from PySide6.QtCore import QEventLoop, QSettings, Qt
    from PySide6.QtWidgets import QApplication

    ini = QSettings.Format.IniFormat
    QSettings.setDefaultFormat(ini)
    for scope in (QSettings.Scope.UserScope, QSettings.Scope.SystemScope):
        QSettings.setPath(ini, scope, str(tmp / "settings"))

    app = QApplication([])
    from qtrequestory.ui import theme
    from qtrequestory.ui.app import configure_application
    from qtrequestory.ui.wizard import FirstRunWizard
    from qtrequestory.ui.workers import JobRunner
    from tests.fakes.fake_core import build_fake_core

    configure_application(app, "0.0-shoot")

    def pump(ms: int = 300) -> None:
        end = time.monotonic() + ms / 1000
        while time.monotonic() < end:
            app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 20)
            time.sleep(0.01)

    runner = JobRunner()
    try:
        for mode in args.modes:
            theme.apply(app, theme.Mode(mode))
            services = build_fake_core(tmp / f"core-{mode}")
            services.config.first_run = True
            services.config.editor = Path(r"C:\Program Files\Notepad++\notepad++.exe")
            services.scheduler.set_legacy(True)
            services.index.set_local_file_count(services.config.load().mirror_root, 7)

            wizard = FirstRunWizard(services, runner)
            wizard.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
            wizard.resize(720, 560)
            wizard.show()
            wizard.restart()
            pump(600)

            def shot(number: int, name: str) -> None:
                pump(300)
                path = args.out / f"{mode}-wizard-{number:02d}-{name}.png"
                wizard.grab().save(str(path))
                print("saved", path)

            shot(1, "archivio")
            wizard.next()
            wizard.environments_page.add_environment()
            shot(2, "ambienti")
            wizard.next()
            shot(3, "automazione")
            wizard.close()
            wizard.deleteLater()

            # A rerun while schtasks has not answered yet.
            services.config.first_run = False
            services.config.config = dataclasses.replace(services.config.config)
            real_status = services.scheduler.status
            services.scheduler.status = lambda: (time.sleep(3), real_status())[1]
            rerun = FirstRunWizard(services, runner)
            rerun.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
            rerun.resize(720, 560)
            rerun.show()
            rerun.restart()
            rerun.next()
            rerun.next()
            pump(300)
            path = args.out / f"{mode}-wizard-04-automazione-verifica.png"
            rerun.grab().save(str(path))
            print("saved", path)
            rerun.close()
            rerun.deleteLater()
            pump(3500)
    finally:
        runner.shutdown(5000)
    return 0


if __name__ == "__main__":
    sys.exit(main())
