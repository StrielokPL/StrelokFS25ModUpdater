from __future__ import annotations

import gc
import logging
import os
import sys
import tempfile
import time
from logging.handlers import RotatingFileHandler

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from . import __version__
from .gui import MainWindow
from .self_update import cleanup_previous_executable
from .storage import data_dir


def _configure_logging() -> None:
    target = data_dir() / "strelok-fs25-mod-updater.log"
    target.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        target,
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    logging.basicConfig(level=logging.INFO, handlers=[handler])


def _exception_hook(exc_type, exc_value, exc_traceback) -> None:
    logging.getLogger(__name__).critical(
        "Nieobsłużony wyjątek", exc_info=(exc_type, exc_value, exc_traceback)
    )
    sys.__excepthook__(exc_type, exc_value, exc_traceback)


def main() -> int:
    smoke_test = "--smoke-test" in sys.argv
    first_run_smoke_test = "--first-run-smoke-test" in sys.argv
    task_smoke_test = "--task-smoke-test" in sys.argv
    cleanup_update_backup = "--cleanup-update-backup" in sys.argv
    temporary_profile = None
    if first_run_smoke_test:
        temporary_profile = tempfile.TemporaryDirectory(prefix="strelok-first-run-")
        if os.name == "nt":
            os.environ["LOCALAPPDATA"] = temporary_profile.name
        else:
            os.environ["XDG_CONFIG_HOME"] = temporary_profile.name
            os.environ["XDG_DATA_HOME"] = temporary_profile.name

    _configure_logging()
    sys.excepthook = _exception_hook
    internal_arguments = {
        "--smoke-test",
        "--first-run-smoke-test",
        "--task-smoke-test",
        "--cleanup-update-backup",
    }
    qt_arguments = [argument for argument in sys.argv if argument not in internal_arguments]
    application = QApplication(qt_arguments)
    application.setApplicationName("Strelok FS25 Mod Updater")
    application.setApplicationVersion(__version__)
    application.setOrganizationName("StrelokPL")

    first_run_verified = False
    task_smoke_verified = False

    def close_first_run_message() -> None:
        widget = application.activeModalWidget()
        if isinstance(widget, QMessageBox):
            widget.accept()
        else:
            QTimer.singleShot(25, close_first_run_message)

    if first_run_smoke_test:
        QTimer.singleShot(100, close_first_run_message)

    window = MainWindow()
    window.show()
    if cleanup_update_backup:
        def cleanup_backup() -> None:
            try:
                cleanup_previous_executable()
            except OSError:
                logging.getLogger(__name__).warning(
                    "Nie udało się usunąć kopii poprzedniej wersji",
                    exc_info=True,
                )

        QTimer.singleShot(1500, cleanup_backup)
    if smoke_test:
        QTimer.singleShot(750, application.quit)
    elif first_run_smoke_test:
        QTimer.singleShot(0, lambda: window.start(check_updates=False))

        def verify_first_run() -> None:
            nonlocal first_run_verified
            first_run_verified = window.isVisible()
            application.quit()

        QTimer.singleShot(400, verify_first_run)
    elif task_smoke_test:
        def run_task_smoke_test() -> None:
            remaining = 64
            failed = False

            def work(_signals):
                time.sleep(0.02)
                return True

            def result(_value) -> None:
                nonlocal remaining
                remaining -= 1
                if remaining == 0:
                    QTimer.singleShot(250, verify_tasks)

            def error(_message: str, _traceback_text: str) -> None:
                nonlocal failed
                failed = True
                application.quit()

            def verify_tasks() -> None:
                nonlocal task_smoke_verified
                task_smoke_verified = (
                    not failed
                    and remaining == 0
                    and not window.active_tasks
                    and window.busy_tasks == 0
                )
                application.quit()

            for _index in range(64):
                window._start_task(work, result, error=error)
            gc.collect()
            QTimer.singleShot(15000, application.quit)

        QTimer.singleShot(0, run_task_smoke_test)
    else:
        QTimer.singleShot(0, window.start)

    exit_code = application.exec()
    if first_run_smoke_test and not first_run_verified:
        return 1
    if task_smoke_test and not task_smoke_verified:
        return 1
    return exit_code
