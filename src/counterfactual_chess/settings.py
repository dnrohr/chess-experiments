"""Small local settings file; no network or analysis cache."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    engine_path: str = ""
    threads: int = 1
    hash_mb: int = 64
    seconds: float = 1.0

    def validate(self) -> None:
        if not 1 <= self.threads <= 256:
            raise ValueError("Threads must be between 1 and 256.")
        if not 1 <= self.hash_mb <= 4096:
            raise ValueError("Hash must be between 1 and 4096 MiB.")
        if not 0.1 <= self.seconds <= 120:
            raise ValueError("Analysis time must be between 0.1 and 120 seconds.")


def settings_path() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / ".config")) / "CounterfactualChess" / "settings.json"


def load_settings(path: Path | None = None) -> Settings:
    try:
        settings = Settings(**json.loads((path or settings_path()).read_text(encoding="utf-8")))
        settings.validate()
        if not isinstance(settings.engine_path, str):
            raise ValueError("Invalid engine path")
        return settings
    except (OSError, ValueError, TypeError):
        return Settings()


def save_settings(settings: Settings, path: Path | None = None) -> None:
    settings.validate()
    target = path or settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(asdict(settings), indent=2), encoding="utf-8")
    temporary.replace(target)
