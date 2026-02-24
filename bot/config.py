from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass
class Settings:
    raw: dict[str, Any]
    root_dir: Path

    @property
    def app(self) -> dict[str, Any]:
        return self.raw.get("app", {})

    @property
    def data(self) -> dict[str, Any]:
        return self.raw.get("data", {})

    @property
    def channels(self) -> dict[str, str]:
        return self.raw.get("channels", {})

    @property
    def warroom(self) -> dict[str, Any]:
        return self.raw.get("warroom", {})

    @property
    def thread_hygiene(self) -> dict[str, Any]:
        return self.raw.get("thread_hygiene", {})

    @property
    def deep_work(self) -> dict[str, Any]:
        return self.raw.get("deep_work", {})

    @property
    def scheduler(self) -> dict[str, str]:
        return self.raw.get("scheduler", {})

    @property
    def dm_assistant(self) -> dict[str, Any]:
        return self.raw.get("dm_assistant", {})

    @property
    def music(self) -> dict[str, Any]:
        return self.raw.get("music", {})

    @property
    def event_reminder(self) -> dict[str, Any]:
        return self.raw.get("event_reminder", {})

    @property
    def curation(self) -> dict[str, Any]:
        return self.raw.get("curation", {})

    @property
    def gemini(self) -> dict[str, Any]:
        # Backward-compat for older settings key.
        return self.raw.get("gemini", self.raw.get("openai", {}))

    @property
    def timezone(self) -> str:
        return os.getenv("TZ") or str(self.app.get("timezone", "Asia/Seoul"))

    @property
    def target_guild_id(self) -> int | None:
        env_value = os.getenv("TARGET_GUILD_ID")
        if env_value and env_value.isdigit():
            return int(env_value)
        value = self.app.get("target_guild_id")
        return int(value) if value else None

    @property
    def data_dir(self) -> Path:
        data_dir_env = os.getenv("DATA_DIR")
        base = Path(data_dir_env) if data_dir_env else Path(self.data.get("base_dir", "./data"))
        if not base.is_absolute():
            base = (self.root_dir / base).resolve()
        return base


def load_settings(root_dir: Path) -> Settings:
    settings_path = root_dir / "config" / "settings.yaml"
    with settings_path.open("r", encoding="utf-8") as fp:
        raw = yaml.safe_load(fp) or {}
    return Settings(raw=raw, root_dir=root_dir)
