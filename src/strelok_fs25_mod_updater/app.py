from __future__ import annotations

import faulthandler
import gc
import logging
import os
import platform
import sys
import tempfile
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, TextIO

from PySide6.QtCore import QMessageLogContext, QtMsgType, QTimer, qInstallMessageHandler
from PySide6.QtWidgets import QApplication, QMessageBox

from . import __version__
from .gui import MainWindow
from .self_update import cleanup_previous_executable
from .storage import data_dir


_fatal_log_stream: TextIO | None = None


def _configure_logging() -> Path:
    target = data_dir() / "strelok-fs25-mod-updater.log"
    target.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        target,
        maxBytes=2 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s [%(threadName)s] %(name)s: %(message)s"
        )
    )
    logging.basicConfig(level=logging.INFO, handlers=[handler], force=True)
    return target


def _configure_fatal_logging() -> Path | None:
    global _fatal_log_stream
    target = data_dir() / "strelok-fs25-mod-updater-fatal.log"
    try:
        _fatal_log_stream = target.open("a", encoding="utf-8")
        _fatal_log_stream.write(
            f"\n--- application start {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n"
        )
        _fatal_log_stream.flush()
        faulthandler.enable(file=_fatal_log_stream, all_threads=True)
    except (OSError, RuntimeError):
        logging.getLogger(__name__).exception("Nie udało się włączyć logu awarii natywnych")
        _fatal_log_stream = None
        return None
    return target


def _qt_message_handler(
    message_type: QtMsgType,
    context: QMessageLogContext,
    message: str,
) -> None:
    logger = logging.getLogger("qt")
    level = {
        QtMsgType.QtDebugMsg: logging.DEBUG,
        QtMsgType.QtInfoMsg: logging.INFO,
        QtMsgType.QtWarningMsg: logging.WARNING,
        QtMsgType.QtCriticalMsg: logging.ERROR,
        QtMsgType.QtFatalMsg: logging.CRITICAL,
    }.get(message_type, logging.WARNING)
    location = ""
    if context.file:
        location = f" file={context.file} line={context.line}"
    logger.log(level, "QT type=%s%s message=%s", message_type.name, location, message)


def _exception_hook(exc_type, exc_value, exc_traceback) -> None:
    logging.getLogger(__name__).critical(
        "Nieobsłużony wyjątek", exc_info=(exc_type, exc_value, exc_traceback)
    )
    if sys.stderr is not None:
        sys.__excepthook__(exc_type, exc_value, exc_traceback)


def _thread_exception_hook(arguments: Any) -> None:
    logging.getLogger(__name__).critical(
        "Nieobsłużony wyjątek w wątku thread=%s",
        getattr(arguments.thread, "name", "unknown"),
        exc_info=(arguments.exc_type, arguments.exc_value, arguments.exc_traceback),
    )


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

    log_path = _configure_logging()
    fatal_log_path = _configure_fatal_logging()
    sys.excepthook = _exception_hook
    threading.excepthook = _thread_exception_hook
    qInstallMessageHandler(_qt_message_handler)
    logger = logging.getLogger(__name__)
    logger.info(
        "APPLICATION START version=%s pid=%d os=%s platform=%s machine=%s "
        "python=%s frozen=%s executable=%s log=%s fatal_log=%s arguments=%s",
        __version__,
        os.getpid(),
        platform.system(),
        platform.platform(),
        platform.machine(),
        platform.python_version(),
        bool(getattr(sys, "frozen", False)),
        sys.executable,
        log_path,
        fatal_log_path or "unavailable",
        sys.argv[1:],
    )
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

    logger.info("QAPPLICATION CREATED arguments=%s", qt_arguments[1:])
    window = MainWindow()
    logger.info("MAIN WINDOW CREATED")
    window.show()
    logger.info("MAIN WINDOW SHOWN")
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
    logger.info("APPLICATION EXIT code=%d", exit_code)
    if first_run_smoke_test and not first_run_verified:
        return 1
    if task_smoke_test and not task_smoke_verified:
        return 1
    return exit_code
