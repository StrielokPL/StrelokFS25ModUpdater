from __future__ import annotations

import logging
import time
import traceback
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, Signal, Slot


class TaskSignals(QObject):
    result = Signal(object)
    error = Signal(str, str)
    status = Signal(str)
    progress = Signal(int, int)
    finished = Signal()


class Task(QRunnable):
    def __init__(
        self,
        function: Callable[[TaskSignals], Any],
        *,
        name: str | None = None,
    ):
        super().__init__()
        self.function = function
        self.name = name or getattr(function, "__name__", "background-task")
        self.signals = TaskSignals()

    @Slot()
    def run(self) -> None:
        logger = logging.getLogger(__name__)
        started = time.monotonic()
        logger.info("TASK START name=%s", self.name)
        try:
            result = self.function(self.signals)
        except BaseException as exc:
            traceback_text = traceback.format_exc()
            logger.error(
                "TASK ERROR name=%s duration=%.3fs error=%s\n%s",
                self.name,
                time.monotonic() - started,
                exc,
                traceback_text,
            )
            self.signals.error.emit(str(exc), traceback_text)
        else:
            logger.info(
                "TASK SUCCESS name=%s duration=%.3fs",
                self.name,
                time.monotonic() - started,
            )
            self.signals.result.emit(result)
        finally:
            logger.info(
                "TASK FINISH name=%s duration=%.3fs",
                self.name,
                time.monotonic() - started,
            )
            self.signals.finished.emit()
