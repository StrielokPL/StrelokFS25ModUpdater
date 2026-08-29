from __future__ import annotations

import shutil
import zipfile
from pathlib import Path


def make_mod_zip(path: Path, version: str, *, extra: dict[str, str] | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    mod_desc = f"""<?xml version="1.0" encoding="utf-8"?>
<modDesc descVersion="96">
    <author>Test</author>
    <version>{version}</version>
    <title><en>Test mod</en></title>
</modDesc>
"""
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("modDesc.xml", mod_desc)
        for name, value in (extra or {}).items():
            archive.writestr(name, value)
    return path


class FakeGitHubClient:
    def __init__(self, source: Path):
        self.source = source

    def download(self, _url: str, target: Path, *, progress=None) -> None:
        shutil.copy2(self.source, target)
        if progress:
            size = target.stat().st_size
            progress(size, size)

