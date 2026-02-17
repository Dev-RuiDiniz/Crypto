from __future__ import annotations

import configparser
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from security.crypto import decrypt_secret, encrypt_secret
from utils.logger import get_logger
from core.audit_log_service import AuditLogService

log = get_logger("credentials_service")


class CredentialsNotFoundError(RuntimeError):
    pass


@dataclass
class ExchangeCredentials:
    tenant_id: str
    exchange: str
    label: str
    api_key: str
    api_secret: str
    passphrase: Optional[str]
    version: int


class ExchangeCredentialsService:
    def __init__(self, cfg: configparser.ConfigParser):
        self.cfg = cfg
        self.sqlite_path = self.cfg.get("GLOBAL", "SQLITE_PATH", fallback="./data/state.db")
        self.audit = AuditLogService(cfg)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.sqlite_path)
        conn.row_factory = sqlite3.Row
        return conn

    def get_credentials(self, tenant_id: str, exchange: str) -> ExchangeCredentials:
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT tenant_id, exchange, label, api_key_encrypted, api_secret_encrypted,
                       passphrase_encrypted, version
                FROM exchange_credentials
                WHERE tenant_id = ? AND lower(exchange) = lower(?) AND status = 'ACTIVE'
                ORDER BY updated_at DESC, id DESC
                LIMIT 1
                """,
                (tenant_id, exchange),
            ).fetchone()
        finally:
            conn.close()

        if not row:
            raise CredentialsNotFoundError(
                f"No active credentials found for tenant='{tenant_id}' exchange='{exchange}'"
            )

        return ExchangeCredentials(
            tenant_id=str(row["tenant_id"]),
            exchange=str(row["exchange"]),
            label=str(row["label"]),
            api_key=decrypt_secret(str(row["api_key_encrypted"])),
            api_secret=decrypt_secret(str(row["api_secret_encrypted"])),
            passphrase=(
                decrypt_secret(str(row["passphrase_encrypted"]))
                if row["passphrase_encrypted"]
                else None
            ),
            version=int(row["version"]),
        )

    def upsert_credentials(
        self,
        tenant_id: str,
        exchange: str,
        label: str,
        api_key: str,
        api_secret: str,
        passphrase: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> int:
        now_iso = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        encrypted_key = encrypt_secret(api_key)
        encrypted_secret = encrypt_secret(api_secret)
        encrypted_passphrase = encrypt_secret(passphrase) if passphrase else None
        last4 = (api_key or "")[-4:].rjust(4, "*")

        conn = self._connect()
        try:
            current = conn.execute(
                """
                SELECT id, version FROM exchange_credentials
                WHERE tenant_id = ? AND lower(exchange) = lower(?) AND label = ?
                LIMIT 1
                """,
                (tenant_id, exchange, label),
            ).fetchone()
            if current:
                version = int(current["version"]) + 1
                conn.execute(
                    """
                    UPDATE exchange_credentials
                    SET api_key_encrypted = ?,
                        api_secret_encrypted = ?,
                        passphrase_encrypted = ?,
                        last4 = ?,
                        status = 'ACTIVE',
                        version = ?,
                        updated_at = ?,
                        updated_by = ?
                    WHERE id = ?
                    """,
                    (
                        encrypted_key,
                        encrypted_secret,
                        encrypted_passphrase,
                        last4,
                        version,
                        now_iso,
                        user_id,
                        int(current["id"]),
                    ),
                )
                resource_id = str(current["id"])
                action = "UPDATE"
            else:
                version = 1
                cur = conn.execute(
                    """
                    INSERT INTO exchange_credentials (
                        tenant_id, exchange, label, api_key_encrypted, api_secret_encrypted,
                        passphrase_encrypted, last4, status, version, created_at, updated_at,
                        created_by, updated_by
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, 'ACTIVE', 1, ?, ?, ?, ?)
                    """,
                    (
                        tenant_id,
                        exchange,
                        label,
                        encrypted_key,
                        encrypted_secret,
                        encrypted_passphrase,
                        last4,
                        now_iso,
                        now_iso,
                        user_id,
                        user_id,
                    ),
                )
                resource_id = str(cur.lastrowid)
                action = "CREATE"
            conn.commit()
        finally:
            conn.close()

        self.audit.write_audit(
            tenant_id=tenant_id,
            action=action,
            resource_type="exchange_credentials",
            resource_id=resource_id,
            user_id=user_id,
            metadata={"exchange": exchange, "label": label, "status": "ACTIVE", "version": version, "last4": last4},
        )
        return version
