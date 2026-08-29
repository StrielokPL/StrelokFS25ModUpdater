from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from strelok_fs25_mod_updater.models import OfficialCatalog  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", type=int)
    parser.add_argument(
        "--path",
        type=Path,
        default=REPOSITORY_ROOT
        / "src"
        / "strelok_fs25_mod_updater"
        / "resources"
        / "official_catalog.json",
    )
    arguments = parser.parse_args()
    with arguments.path.open("r", encoding="utf-8") as handle:
        catalog = OfficialCatalog.from_dict(json.load(handle))
    if arguments.version is not None and catalog.catalog_version != arguments.version:
        parser.error(
            f"catalogVersion={catalog.catalog_version}, oczekiwano {arguments.version}"
        )
    print(
        f"Katalog v{catalog.catalog_version}: {len(catalog.mods)} wpisów, "
        f"schemat {catalog.schema_version}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
