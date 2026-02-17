from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


APP_FOLDER_NAME = "TradingBot"


@dataclass(frozen=True)
class AppPaths:
    base_dir: Path
    data_dir: Path
    log_dir: Path
    db_path: Path


def _local_appdata_root() -> Path:
    local_appdata = os.getenv("LOCALAPPDATA", "").strip()
    if local_appdata:
        return Path(local_appdata)
    # Fallback para ambientes não-Windows (dev/CI)
    return Path.home() / ".local" / "share"


def resolve_app_paths() -> AppPaths:
    base_dir = _local_appdata_root() / APP_FOLDER_NAME
    data_dir = base_dir / "data"
    log_dir = base_dir / "logs"
    db_path = data_dir / "state.db"
    return AppPaths(
        base_dir=base_dir,
        data_dir=data_dir,
        log_dir=log_dir,
        db_path=db_path,
    )


def ensure_runtime_dirs(paths: AppPaths) -> None:
    paths.base_dir.mkdir(parents=True, exist_ok=True)
    paths.data_dir.mkdir(parents=True, exist_ok=True)
    paths.log_dir.mkdir(parents=True, exist_ok=True)
