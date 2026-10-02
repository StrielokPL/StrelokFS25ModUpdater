"""Frozen integration probe: update/restart after the originating process exits."""
import json
import os
from pathlib import Path
import shutil
import sys
import time

from strelok_fs25_mod_updater.self_update import (
    ApplicationUpdate, PreparedApplicationUpdate,
)
from strelok_fs25_mod_updater.versioning import ModVersion
from strelok_fs25_mod_updater.update_helper import WINDOWS_HELPER_NAME

root = Path(sys.executable).parent
if "--cleanup-update-backup" in sys.argv:
    # Stay alive past the old bootloader's cleanup, then verify our runtime still exists.
    time.sleep(2)
    assert (Path(sys._MEIPASS) / "python312.dll").is_file()
    (root / "restarted.json").write_text(json.dumps({"extraction": sys._MEIPASS}))
else:
    (root / "original.json").write_text(json.dumps({"extraction": sys._MEIPASS}))
    staged = root / "staged update.exe"
    shutil.copy2(sys.executable, staged)
    update = ApplicationUpdate("v2", ModVersion.parse("2"), False, "", "", "probe.exe", "https://example.invalid")
    PreparedApplicationUpdate(update, staged, Path(sys.executable), "nt", root / WINDOWS_HELPER_NAME).apply_and_restart()
