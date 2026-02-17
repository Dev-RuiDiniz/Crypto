from __future__ import annotations

import configparser
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from security.crypto import decrypt_secret, encrypt_secret
from utils.logger import get_logger
from core.audit_log_service import AuditLogService

log = get_logger("credentials_service")


class CredentialsNotFoundError(RuntimeError):
    pass


class CredentialsConflictError(RuntimeError):
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


@dataclass
class ExchangeCredentialMetadata:
    id: int
    exchange: str
    label: str
    last4: str
    status: str
    version: int
    updated_at: str


class ExchangeCredentialsService:
    def __init__(self, cfg: configparser.ConfigParser):
        self.cfg = cfg
        self.sqlite_path = self.cfg.get("GLOBAL", "SQLITE_PATH", fallback="./data/state.db")
        self.audit = AuditLogService(cfg)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.sqlite_path)
        conn.row_factory = sqlite3.Row
        return conn

    def list_credentials(self, tenant_id: str) -> list[ExchangeCredentialMetadata]:
        conn = self._connect()
        try:
            rows = conn.execute(
                """
                SELECT id, exchange, label, last4, status, version, updated_at
                FROM exchange_credentials
                WHERE tenant_id = ?
                ORDER BY updated_at DESC, id DESC
                """,
                (tenant_id,),
            ).fetchall()
        finally:
            conn.close()

        return [
            ExchangeCredentialMetadata(
                id=int(row["id"]),
                exchange=str(row["exchange"]),
                label=str(row["label"]),
                last4=str(row["last4"]),
                status=str(row["status"]),
                version=int(row["version"]),
                updated_at=str(row["updated_at"]),
            )
            for row in rows
        ]

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

    def get_credentials_by_id(self, tenant_id: str, credential_id: int) -> ExchangeCredentials:
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT tenant_id, exchange, label, api_key_encrypted, api_secret_encrypted,
                       passphrase_encrypted, version
                FROM exchange_credentials
                WHERE tenant_id = ? AND id = ? AND status = 'ACTIVE'
                LIMIT 1
                """,
                (tenant_id, credential_id),
            ).fetchone()
        finally:
            conn.close()

        if not row:
            raise CredentialsNotFoundError(f"Credential not found for tenant='{tenant_id}' id='{credential_id}'")

        return ExchangeCredentials(
            tenant_id=str(row["tenant_id"]),
            exchange=str(row["exchange"]),
            label=str(row["label"]),
            api_key=decrypt_secret(str(row["api_key_encrypted"])),
            api_secret=decrypt_secret(str(row["api_secret_encrypted"])),
            passphrase=(decrypt_secret(str(row["passphrase_encrypted"])) if row["passphrase_encrypted"] else None),
            version=int(row["version"]),
        )

    def get_metadata_by_id(self, tenant_id: str, credential_id: int) -> ExchangeCredentialMetadata:
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT id, exchange, label, last4, status, version, updated_at
                FROM exchange_credentials
                WHERE tenant_id = ? AND id = ?
                LIMIT 1
                """,
                (tenant_id, credential_id),
            ).fetchone()
        finally:
            conn.close()
        if not row:
            raise CredentialsNotFoundError(f"Credential not found for tenant='{tenant_id}' id='{credential_id}'")
        return ExchangeCredentialMetadata(
            id=int(row["id"]),
            exchange=str(row["exchange"]),
            label=str(row["label"]),
            last4=str(row["last4"]),
            status=str(row["status"]),
            version=int(row["version"]),
            updated_at=str(row["updated_at"]),
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
        created = self.create_credentials(tenant_id, exchange, label, api_key, api_secret, passphrase, user_id)
        return created.version

    def create_credentials(
        self,
        tenant_id: str,
        exchange: str,
        label: str,
        api_key: str,
        api_secret: str,
        passphrase: Optional[str],
        user_id: Optional[str],
    ) -> ExchangeCredentialMetadata:
        now_iso = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        encrypted_key = encrypt_secret(api_key)
        encrypted_secret = encrypt_secret(api_secret)
        encrypted_passphrase = encrypt_secret(passphrase) if passphrase else None
        last4 = (api_key or "")[-4:].rjust(4, "*")

        conn = self._connect()
        try:
            try:
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
            except sqlite3.IntegrityError as exc:
                raise CredentialsConflictError("Credential label already exists for exchange") from exc
            credential_id = int(cur.lastrowid)
            conn.commit()
        finally:
            conn.close()

        self.audit.write_audit(
            tenant_id=tenant_id,
            action="CREATE",
            resource_type="exchange_credentials",
            resource_id=str(credential_id),
            user_id=user_id,
            metadata={"exchange": exchange, "label": label, "status": "ACTIVE", "version": 1, "last4": last4},
        )
        return self.get_metadata_by_id(tenant_id, credential_id)

    def update_credentials(
        self,
        tenant_id: str,
        credential_id: int,
        *,
        label: Optional[str],
        status: Optional[str],
        api_key: Optional[str],
        api_secret: Optional[str],
        passphrase: Optional[str],
        user_id: Optional[str],
    ) -> ExchangeCredentialMetadata:
        now_iso = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        conn = self._connect()
        try:
            row = conn.execute(
                """
                SELECT * FROM exchange_credentials WHERE tenant_id = ? AND id = ? LIMIT 1
                """,
                (tenant_id, credential_id),
            ).fetchone()
            if not row:
                raise CredentialsNotFoundError(f"Credential not found for tenant='{tenant_id}' id='{credential_id}'")

            changed_fields: list[str] = []
            current_version = int(row["version"])
            next_version = current_version

            new_label = str(label) if label is not None else str(row["label"])
            if new_label != str(row["label"]):
                changed_fields.append("label")

            new_status = str(status).upper() if status is not None else str(row["status"]).upper()
            if new_status != str(row["status"]).upper():
                changed_fields.append("status")

            key_encrypted = str(row["api_key_encrypted"])
            if api_key is not None:
                key_encrypted = encrypt_secret(api_key)
                changed_fields.append("apiKey")

            secret_encrypted = str(row["api_secret_encrypted"])
            if api_secret is not None:
                secret_encrypted = encrypt_secret(api_secret)
                changed_fields.append("apiSecret")

            passphrase_encrypted = row["passphrase_encrypted"]
            if passphrase is not None:
                passphrase_encrypted = encrypt_secret(passphrase) if passphrase else None
                changed_fields.append("passphrase")

            has_secret_rotation = any(f in {"apiKey", "apiSecret", "passphrase"} for f in changed_fields)
            if has_secret_rotation:
                next_version = current_version + 1

            new_last4 = str(row["last4"])
            if api_key is not None:
                new_last4 = (api_key or "")[-4:].rjust(4, "*")

            conn.execute(
                """
                UPDATE exchange_credentials
                SET label = ?,
                    status = ?,
                    api_key_encrypted = ?,
                    api_secret_encrypted = ?,
                    passphrase_encrypted = ?,
                    last4 = ?,
                    version = ?,
                    updated_at = ?,
                    updated_by = ?
                WHERE id = ? AND tenant_id = ?
                """,
                (
                    new_label,
                    new_status,
                    key_encrypted,
                    secret_encrypted,
                    passphrase_encrypted,
                    new_last4,
                    next_version,
                    now_iso,
                    user_id,
                    credential_id,
                    tenant_id,
                ),
            )
            conn.commit()
        finally:
            conn.close()

        metadata = self.get_metadata_by_id(tenant_id, credential_id)
        self.audit.write_audit(
            tenant_id=tenant_id,
            action="UPDATE",
            resource_type="exchange_credentials",
            resource_id=str(credential_id),
            user_id=user_id,
            metadata={
                "exchange": metadata.exchange,
                "label": metadata.label,
                "status": metadata.status,
                "version": metadata.version,
                "changedFields": changed_fields,
            },
        )
        return metadata

    def revoke_credentials(self, tenant_id: str, credential_id: int, user_id: Optional[str]) -> None:
        now_iso = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        conn = self._connect()
        try:
            row = conn.execute(
                "SELECT version FROM exchange_credentials WHERE tenant_id = ? AND id = ? LIMIT 1",
                (tenant_id, credential_id),
            ).fetchone()
            if not row:
                raise CredentialsNotFoundError(f"Credential not found for tenant='{tenant_id}' id='{credential_id}'")
            next_version = int(row["version"]) + 1
            conn.execute(
                """
                UPDATE exchange_credentials
                SET status = 'REVOKED', version = ?, updated_at = ?, updated_by = ?
                WHERE tenant_id = ? AND id = ?
                """,
                (next_version, now_iso, user_id, tenant_id, credential_id),
            )
            conn.commit()
        finally:
            conn.close()

        self.audit.write_audit(
            tenant_id=tenant_id,
            action="REVOKE",
            resource_type="exchange_credentials",
            resource_id=str(credential_id),
            user_id=user_id,
            metadata={"status": "REVOKED", "version": next_version},
        )

    def write_test_audit(
        self,
        tenant_id: str,
        credential_id: int,
        user_id: Optional[str],
        *,
        ok: bool,
        latency_ms: Optional[int],
        error_code: Optional[str],
        category: Optional[str],
        exchange: Optional[str] = None,
        label: Optional[str] = None,
    ) -> None:
        metadata: dict[str, Any] = {"ok": bool(ok)}
        if latency_ms is not None:
            metadata["latencyMs"] = int(latency_ms)
        if error_code:
            metadata["errorCode"] = error_code
        if category:
            metadata["category"] = category
        if exchange:
            metadata["exchange"] = exchange
        if label:
            metadata["label"] = label

        self.audit.write_audit(
            tenant_id=tenant_id,
            action="TEST",
            resource_type="exchange_credentials",
            resource_id=str(credential_id),
            user_id=user_id,
            metadata=metadata,
        )
