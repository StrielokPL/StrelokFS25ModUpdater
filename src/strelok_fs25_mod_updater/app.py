from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from . import __version__
from .gui import MainWindow
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
    _configure_logging()
    sys.excepthook = _exception_hook
    smoke_test = "--smoke-test" in sys.argv
    qt_arguments = [argument for argument in sys.argv if argument != "--smoke-test"]
    application = QApplication(qt_arguments)
    application.setApplicationName("Strelok FS25 Mod Updater")
    application.setApplicationVersion(__version__)
    application.setOrganizationName("StrelokPL")
    window = MainWindow(smoke_test=smoke_test)
    window.show()
    if smoke_test:
        QTimer.singleShot(750, application.quit)
    return application.exec()
