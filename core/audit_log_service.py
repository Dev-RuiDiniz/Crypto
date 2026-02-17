from __future__ import annotations

import configparser
import sqlite3
from datetime import datetime
from typing import Any, Optional

from security.redaction import redact_value, safe_json


class AuditLogService:
    def __init__(self, cfg: configparser.ConfigParser):
        self.cfg = cfg
        self.sqlite_path = self.cfg.get("GLOBAL", "SQLITE_PATH", fallback="./data/state.db")

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.sqlite_path)

    def write_audit(
        self,
        tenant_id: str,
        action: str,
        resource_type: str,
        resource_id: str,
        user_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        payload = safe_json(redact_value(metadata or {}))
        conn = self._connect()
        try:
            conn.execute(
                """
                INSERT INTO audit_logs (
                    tenant_id, action, resource_type, resource_id, user_id, created_at, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    tenant_id,
                    str(action).upper(),
                    resource_type,
                    resource_id,
                    user_id,
                    datetime.utcnow().isoformat(timespec="seconds") + "Z",
                    payload,
                ),
            )
            conn.commit()
        finally:
            conn.close()
