from __future__ import annotations

import argparse
import ctypes
import logging
import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from .storage import data_dir
from .process_environment import independent_process_environment


HELPER_LOG_NAME = "strelok-fs25-mod-updater-helper.log"
UPDATE_CLEANUP_ARGUMENT = "--cleanup-update-backup"
WINDOWS_HELPER_NAME = "StrelokFS25ModUpdaterHelper.exe"

WaitCallback = Callable[[int, float], None]
LaunchCallback = Callable[[Path, list[str]], None]


class UpdateHelperError(RuntimeError):
    pass


def _configure_logging(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.FileHandler(directory / HELPER_LOG_NAME, encoding="utf-8")],
        force=True,
    )


def wait_for_process(process_id: int, timeout: float = 120.0) -> None:
    if os.name != "nt":
        raise UpdateHelperError("Helper aktualizacji jest przeznaczony dla Windowsa")

    synchronize = 0x00100000
    wait_timeout = 0x00000102
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.WaitForSingleObject.restype = ctypes.c_uint32
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]

    handle = kernel32.OpenProcess(synchronize, False, process_id)
    if not handle:
        logging.info("Proces %d już nie działa", process_id)
        return
    try:
        result = kernel32.WaitForSingleObject(handle, int(timeout * 1000))
    finally:
        kernel32.CloseHandle(handle)
    if result == wait_timeout:
        raise UpdateHelperError(
            f"Program nie zakończył się w ciągu {timeout:g} sekund"
        )
    if result != 0:
        raise UpdateHelperError(f"Nie udało się zaczekać na program: kod {result}")


def _retry(operation: Callable[[], None], *, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while True:
        try:
            operation()
            return
        except OSError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.25)


def _remove(path: Path) -> None:
    if path.exists():
        _retry(path.unlink)


def _replace(source: Path, destination: Path) -> None:
    _retry(lambda: os.replace(source, destination))


def launch_application(executable: Path, arguments: list[str]) -> None:
    creation_flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(
        [str(executable), *arguments],
        cwd=executable.parent,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=creation_flags,
        env=independent_process_environment(),
    )


def _validated_paths(
    target: Path,
    staged: Path,
    backup: Path,
) -> tuple[Path, Path, Path]:
    target = target.resolve()
    staged = staged.resolve()
    backup = backup.resolve()
    if not target.is_file():
        raise UpdateHelperError(f"Nie znaleziono aktualnego programu: {target}")
    if not staged.is_file():
        raise UpdateHelperError(f"Nie znaleziono pobranej aktualizacji: {staged}")
    if target.parent != staged.parent or target.parent != backup.parent:
        raise UpdateHelperError("Pliki aktualizacji muszą znajdować się w jednym folderze")
    expected_backup = target.with_name(f".{target.name}.previous")
    if backup != expected_backup:
        raise UpdateHelperError("Nieprawidłowa ścieżka kopii poprzedniej wersji")
    return target, staged, backup


def perform_update(
    *,
    old_process_id: int,
    target: Path,
    staged: Path,
    backup: Path,
    wait: WaitCallback = wait_for_process,
    launch: LaunchCallback = launch_application,
) -> None:
    target, staged, backup = _validated_paths(target, staged, backup)
    logging.info(
        "Rozpoczęcie aktualizacji pid=%d target=%s staged=%s backup=%s",
        old_process_id,
        target,
        staged,
        backup,
    )
    wait(old_process_id, 120.0)
    _remove(backup)
    _replace(target, backup)
    try:
        _replace(staged, target)
        launch(target, [UPDATE_CLEANUP_ARGUMENT])
    except BaseException as exc:
        logging.exception("Aktualizacja nie powiodła się; przywracanie poprzedniej wersji")
        _remove(target)
        if backup.exists():
            _replace(backup, target)
            try:
                launch(target, [])
            except OSError:
                logging.exception("Nie udało się ponownie uruchomić poprzedniej wersji")
        raise UpdateHelperError(f"Nie udało się zastosować aktualizacji: {exc}") from exc
    logging.info("Aktualizacja zakończona; uruchomiono nową wersję")


def _show_error(message: str) -> None:
    if os.name == "nt":
        ctypes.windll.user32.MessageBoxW(
            None,
            message,
            "Błąd aktualizacji Strelok FS25 Mod Updater",
            0x10,
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Helper aktualizacji aplikacji")
    parser.add_argument("--old-pid", type=int)
    parser.add_argument("--target", type=Path)
    parser.add_argument("--staged", type=Path)
    parser.add_argument("--backup", type=Path)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--ready-file", type=Path)
    parser.add_argument("--proceed-file", type=Path)
    return parser


def main(arguments: list[str] | None = None) -> int:
    options = _parser().parse_args(arguments)
    if options.self_test:
        return 0
    if None in (options.old_pid, options.target, options.staged, options.backup):
        return 2
    if options.old_pid <= 0:
        return 2
    try:
        _configure_logging(data_dir())
    except OSError:
        _configure_logging(options.target.resolve().parent)
    try:
        _validated_paths(options.target, options.staged, options.backup)
        if options.ready_file is not None or options.proceed_file is not None:
            expected_ready = options.staged.with_suffix(".ready").resolve()
            expected_proceed = options.staged.with_suffix(".proceed").resolve()
            if (options.ready_file is None or options.proceed_file is None
                    or options.ready_file.resolve() != expected_ready
                    or options.proceed_file.resolve() != expected_proceed):
                raise UpdateHelperError("Nieprawidłowe ścieżki potwierdzenia aktualizacji")
            expected_ready.write_text("ready", encoding="utf-8")
            try:
                deadline = time.monotonic() + 40.0
                while not expected_proceed.is_file():
                    if time.monotonic() >= deadline:
                        raise UpdateHelperError("Aplikacja nie potwierdziła rozpoczęcia aktualizacji")
                    time.sleep(0.1)
            finally:
                expected_ready.unlink(missing_ok=True)
                expected_proceed.unlink(missing_ok=True)
        perform_update(
            old_process_id=options.old_pid,
            target=options.target,
            staged=options.staged,
            backup=options.backup,
        )
    except BaseException as exc:
        logging.exception("Helper zakończył się błędem")
        _show_error(str(exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
