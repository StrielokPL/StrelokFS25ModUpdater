# -*- mode: python ; coding: utf-8 -*-

import sys
from pathlib import Path
import os

from PyInstaller.utils.hooks import collect_data_files


datas = collect_data_files("strelok_fs25_mod_updater")

linux_binaries = []
if sys.platform == "linux":
    candidates = [Path(directory) / "libxcb-cursor.so.0" for directory in
                  os.environ.get("LD_LIBRARY_PATH", "").split(":") if directory]
    candidates.extend([Path("/usr/lib/x86_64-linux-gnu/libxcb-cursor.so.0"),
                       Path("/lib/x86_64-linux-gnu/libxcb-cursor.so.0")])
    cursor = next((path for path in candidates if path.is_file()), None)
    if cursor is None:
        raise SystemExit("Linux GUI build requires libxcb-cursor0 (install before building)")
    linux_binaries.append((str(cursor), "."))

analysis = Analysis(
    ["launcher.py"],
    pathex=["../src"],
    binaries=linux_binaries,
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="StrelokFS25ModUpdater",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    version="version_info.txt" if sys.platform == "win32" else None,
)
