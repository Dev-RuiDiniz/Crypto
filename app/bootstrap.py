from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Tuple

from app.paths import AppPaths

MASTER_KEY_ENV = "EXCHANGE_CREDENTIALS_MASTER_KEY"


def _is_valid_master_key(value: str) -> bool:
    raw = str(value or "").strip()
    if len(raw) != 64:
        return False
    try:
        bytes.fromhex(raw)
    except Exception:
        return False
    return True


def ensure_master_key(paths: AppPaths) -> Tuple[str, str]:
    """
    Garante chave AES-256 para o cofre de credenciais.
    Ordem:
    1) env EXCHANGE_CREDENTIALS_MASTER_KEY (se válida)
    2) arquivo LOCALAPPDATA\\TradingBot\\data\\master_key.txt
    3) gera nova chave e persiste no arquivo
    """
    env_key = os.getenv(MASTER_KEY_ENV, "").strip()
    if _is_valid_master_key(env_key):
        return env_key, "env"

    key_file: Path = paths.data_dir / "master_key.txt"
    if key_file.exists():
        file_key = key_file.read_text(encoding="utf-8").strip()
        if _is_valid_master_key(file_key):
            os.environ[MASTER_KEY_ENV] = file_key
            return file_key, str(key_file)

    new_key = secrets.token_hex(32)  # 32 bytes => 64 hex chars
    key_file.write_text(new_key, encoding="utf-8")
    os.environ[MASTER_KEY_ENV] = new_key
    return new_key, str(key_file)
