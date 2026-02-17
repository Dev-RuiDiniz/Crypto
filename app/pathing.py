from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from app.paths import resolve_app_paths


@dataclass(frozen=True)
class ConfigResolution:
    path: Path
    tried_paths: List[Path]


class ConfigResolutionError(FileNotFoundError):
    def __init__(self, config_value: str, tried_paths: List[Path]):
        self.config_value = config_value
        self.tried_paths = tried_paths
        tried = "\n".join(f"  - {p}" for p in tried_paths)
        super().__init__(
            "Arquivo de configuração não encontrado: "
            f"{config_value}\nCaminhos tentados:\n{tried}"
        )


def get_work_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def get_data_dir() -> Path:
    return resolve_app_paths().data_dir


def resolve_config_path(config_value: str, must_exist: bool = True) -> ConfigResolution:
    raw_value = (config_value or "config.txt").strip() or "config.txt"
    expanded = Path(os.path.expandvars(os.path.expanduser(raw_value)))

    tried_paths: List[Path] = []
    if expanded.is_absolute():
        tried_paths.append(expanded)
    else:
        data_path = get_data_dir() / expanded
        work_path = get_work_dir() / expanded
        tried_paths.extend([data_path, work_path])

    normalized = [path.resolve() for path in tried_paths]

    if must_exist:
        for candidate in normalized:
            if candidate.exists() and candidate.is_file():
                return ConfigResolution(path=candidate, tried_paths=normalized)
        raise ConfigResolutionError(raw_value, normalized)

    return ConfigResolution(path=normalized[0], tried_paths=normalized)


def _default_config_candidates() -> List[Path]:
    candidates: List[Path] = []
    if getattr(sys, "_MEIPASS", None):
        candidates.append(Path(str(sys._MEIPASS)) / "config.txt")
    candidates.append(get_work_dir() / "config.txt")
    return [path.resolve() for path in candidates]


def ensure_default_config_in_data_dir() -> Optional[Path]:
    data_dir = get_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    target = (data_dir / "config.txt").resolve()
    if target.exists():
        return None

    for candidate in _default_config_candidates():
        if candidate.exists() and candidate.is_file():
            shutil.copy2(candidate, target)
            return target
    return None
