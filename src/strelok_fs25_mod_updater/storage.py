from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .models import CatalogMod, ReleaseChannel, SourceKind


APP_DIR_NAME = "StrelokFS25ModUpdater"


def config_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / APP_DIR_NAME


def data_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / APP_DIR_NAME


def atomic_write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return default


@dataclass
class AppSettings:
    mods_directory: str = ""
    channels: dict[str, str] = field(default_factory=dict)
    pinned_versions: dict[str, str] = field(default_factory=dict)
    first_run_warning_seen: bool = False

    def channel_for(self, mod_id: str) -> ReleaseChannel:
        try:
            channel = ReleaseChannel(
                self.channels.get(mod_id, ReleaseChannel.STABLE.value)
            )
        except ValueError:
            return ReleaseChannel.STABLE
        if channel is ReleaseChannel.PINNED and not self.pinned_version_for(mod_id):
            return ReleaseChannel.STABLE
        return channel

    def set_channel(self, mod_id: str, channel: ReleaseChannel) -> None:
        self.channels[mod_id] = channel.value

    def pinned_version_for(self, mod_id: str) -> str:
        return self.pinned_versions.get(mod_id, "")

    def set_pinned_version(self, mod_id: str, tag: str) -> None:
        self.channels[mod_id] = ReleaseChannel.PINNED.value
        self.pinned_versions[mod_id] = tag

    def clear_pinned_version(self, mod_id: str) -> None:
        self.pinned_versions.pop(mod_id, None)


class SettingsStore:
    def __init__(self, path: Path | None = None):
        self.path = path or config_dir() / "settings.json"

    def load(self) -> AppSettings:
        raw = read_json(self.path, {})
        if not isinstance(raw, dict):
            return AppSettings()
        return AppSettings(
            mods_directory=str(raw.get("mods_directory", "")),
            channels={str(key): str(value) for key, value in raw.get("channels", {}).items()},
            pinned_versions={
                str(key): str(value)
                for key, value in raw.get("pinned_versions", {}).items()
            },
            first_run_warning_seen=bool(raw.get("first_run_warning_seen", False)),
        )

    def save(self, settings: AppSettings) -> None:
        atomic_write_json(self.path, asdict(settings))


class ExternalSourcesStore:
    def __init__(self, path: Path | None = None):
        self.path = path or config_dir() / "external_sources.json"

    def load(self) -> tuple[CatalogMod, ...]:
        raw = read_json(self.path, [])
        if not isinstance(raw, list):
            return ()
        result: list[CatalogMod] = []
        for item in raw:
            try:
                result.append(CatalogMod.from_dict(item, source=SourceKind.EXTERNAL))
            except (TypeError, ValueError):
                continue
        return tuple(result)

    def save(self, mods: list[CatalogMod] | tuple[CatalogMod, ...]) -> None:
        atomic_write_json(self.path, [mod.to_dict() for mod in mods])


class HistoryStore:
    def __init__(self, path: Path | None = None):
        self.path = path or data_dir() / "history.json"

    def append(self, event: dict[str, Any]) -> None:
        history = read_json(self.path, [])
        if not isinstance(history, list):
            history = []
        history.append(event)
        atomic_write_json(self.path, history[-500:])

    def load(self) -> list[dict[str, Any]]:
        value = read_json(self.path, [])
        return value if isinstance(value, list) else []
