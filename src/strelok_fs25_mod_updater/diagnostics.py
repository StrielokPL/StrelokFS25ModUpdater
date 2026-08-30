from __future__ import annotations

import json
import os
import platform
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .storage import config_dir, data_dir


LOG_PREFIX = "strelok-fs25-mod-updater"


def diagnostic_information(extra: dict[str, Any] | None = None) -> dict[str, Any]:
    information: dict[str, Any] = {
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "applicationVersion": __version__,
        "operatingSystem": platform.platform(),
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "pythonVersion": platform.python_version(),
        "executable": sys.executable,
        "frozen": bool(getattr(sys, "frozen", False)),
        "processId": os.getpid(),
        "configDirectory": str(config_dir()),
        "dataDirectory": str(data_dir()),
    }
    if extra:
        information["applicationState"] = extra
    return information


def create_diagnostic_bundle(
    target: Path,
    *,
    source_directory: Path | None = None,
    extra: dict[str, Any] | None = None,
) -> Path:
    source = source_directory or data_dir()
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "diagnostics.json",
            json.dumps(diagnostic_information(extra), ensure_ascii=False, indent=2) + "\n",
        )
        if source.is_dir():
            for path in sorted(source.glob(f"{LOG_PREFIX}*.log*")):
                if path.is_file():
                    archive.write(path, f"logs/{path.name}")
    return target
