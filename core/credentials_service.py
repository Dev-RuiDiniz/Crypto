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


@dataclass
class ActiveExchangeCredential:
    credential_id: int
    tenant_id: str
    exchange: str
    label: str
    api_key: str
    api_secret: str
    passphrase: Optional[str]
    status: str
    version: int
    updated_at: str


@dataclass
class ExchangeStatusMetadata:
    tenant_id: str
    exchange: str
    label: str
    status: str
    credential_id: Optional[int]
    credential_version: Optional[int]
    last_test_ok: Optional[bool]
    last_test_at: Optional[str]
    last_test_latency_ms: Optional[int]
    last_error_code: Optional[str]
    last_error_category: Optional[str]
    updated_at: str


class ExchangeCredentialsService:
    def __init__(self, cfg: configparser.ConfigParser):
        self.cfg = cfg
        self.sqlite_path = self.cfg.get("GLOBAL", "SQLITE_PATH", fallback="./data/state.db")
        self.audit = AuditLogService(cfg)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.sqlite_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA busy_timeout = 30000")
        except Exception:
            pass
        return conn

    def _ensure_exchange_credentials_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS exchange_credentials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL,
                exchange TEXT NOT NULL,
                label TEXT NOT NULL,
                api_key_encrypted TEXT NOT NULL,
                api_secret_encrypted TEXT NOT NULL,
                passphrase_encrypted TEXT,
                last4 TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'ACTIVE',
                version INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                created_by TEXT,
                updated_by TEXT
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_exchange_credentials_tenant_exchange_status ON exchange_credentials(tenant_id, exchange, status)"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS ux_exchange_credentials_tenant_exchange_label ON exchange_credentials(tenant_id, exchange, label)"
        )

    def _ensure_exchange_status_schema(self, conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS exchange_status (
                tenant_id TEXT NOT NULL,
                exchange TEXT NOT NULL,
                label TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'UNKNOWN',
                credential_id INTEGER,
                credential_version INTEGER,
                last_test_ok INTEGER,
                last_test_at TEXT,
                last_test_latency_ms INTEGER,
                last_error_code TEXT,
                last_error_category TEXT,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (tenant_id, exchange)
            )
            """
        )

    def _upsert_exchange_status(
        self,
        conn: sqlite3.Connection,
        *,
        tenant_id: str,
        exchange: str,
        label: str,
        status: str,
        credential_id: Optional[int],
        credential_version: Optional[int],
        updated_at: str,
        last_test_ok: Optional[bool] = None,
        last_test_at: Optional[str] = None,
        last_test_latency_ms: Optional[int] = None,
        last_error_code: Optional[str] = None,
        last_error_category: Optional[str] = None,
    ) -> None:
        self._ensure_exchange_status_schema(conn)
        existing = conn.execute(
            """
            SELECT last_test_ok, last_test_at, last_test_latency_ms, last_error_code, last_error_category
            FROM exchange_status
            WHERE tenant_id = ? AND lower(exchange) = lower(?)
            LIMIT 1
            """,
            (tenant_id, exchange),
        ).fetchone()

        if existing is not None:
            if last_test_ok is None:
                val = existing["last_test_ok"]
                last_test_ok = None if val is None else bool(int(val))
            if last_test_at is None:
                last_test_at = str(existing["last_test_at"] or "") or None
            if last_test_latency_ms is None:
                val = existing["last_test_latency_ms"]
                last_test_latency_ms = None if val is None else int(val)
            if last_error_code is None:
                last_error_code = str(existing["last_error_code"] or "") or None
            if last_error_category is None:
                last_error_category = str(existing["last_error_category"] or "") or None

        conn.execute(
            """
            INSERT INTO exchange_status (
                tenant_id, exchange, label, status, credential_id, credential_version,
                last_test_ok, last_test_at, last_test_latency_ms, last_error_code, last_error_category, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(tenant_id, exchange) DO UPDATE SET
                label=excluded.label,
                status=excluded.status,
                credential_id=excluded.credential_id,
                credential_version=excluded.credential_version,
                last_test_ok=excluded.last_test_ok,
                last_test_at=excluded.last_test_at,
                last_test_latency_ms=excluded.last_test_latency_ms,
                last_error_code=excluded.last_error_code,
                last_error_category=excluded.last_error_category,
                updated_at=excluded.updated_at
            """,
            (
                tenant_id,
                exchange,
                label,
                status,
                credential_id,
                credential_version,
                None if last_test_ok is None else (1 if bool(last_test_ok) else 0),
                last_test_at,
                last_test_latency_ms,
                last_error_code,
                last_error_category,
                updated_at,
            ),
        )

    def list_exchange_status(self, tenant_id: str) -> list[ExchangeStatusMetadata]:
        conn = self._connect()
        try:
            self._ensure_exchange_credentials_schema(conn)
            self._ensure_exchange_status_schema(conn)
            rows = conn.execute(
                """
                SELECT id, exchange, label, status, version, updated_at
                FROM exchange_credentials
                WHERE tenant_id = ?
                ORDER BY updated_at DESC, id DESC
                """,
                (tenant_id,),
            ).fetchall()
            seen: set[str] = set()
            try:
                for row in rows:
                    ex = str(row["exchange"] or "").strip().lower()
                    if not ex or ex in seen:
                        continue
                    seen.add(ex)
                    self._upsert_exchange_status(
                        conn,
                        tenant_id=tenant_id,
                        exchange=ex,
                        label=str(row["label"] or ""),
                        status=str(row["status"] or "UNKNOWN").upper(),
                        credential_id=int(row["id"]) if row["id"] is not None else None,
                        credential_version=int(row["version"]) if row["version"] is not None else None,
                        updated_at=str(row["updated_at"] or datetime.utcnow().isoformat(timespec="seconds") + "Z"),
                    )
                conn.commit()
            except sqlite3.OperationalError as exc:
                if "locked" in str(exc).lower():
                    conn.rollback()
                    log.warning("list_exchange_status lock timeout tenant_id=%s", tenant_id)
                else:
                    raise

            status_rows = conn.execute(
                """
                SELECT tenant_id, exchange, label, status, credential_id, credential_version,
                       last_test_ok, last_test_at, last_test_latency_ms, last_error_code, last_error_category, updated_at
                FROM exchange_status
                WHERE tenant_id = ?
                ORDER BY exchange ASC
                """,
                (tenant_id,),
            ).fetchall()
        finally:
            conn.close()

        out: list[ExchangeStatusMetadata] = []
        for row in status_rows:
            test_ok_raw = row["last_test_ok"]
            out.append(
                ExchangeStatusMetadata(
                    tenant_id=str(row["tenant_id"] or tenant_id),
                    exchange=str(row["exchange"] or ""),
                    label=str(row["label"] or ""),
                    status=str(row["status"] or "UNKNOWN"),
                    credential_id=None if row["credential_id"] is None else int(row["credential_id"]),
                    credential_version=None if row["credential_version"] is None else int(row["credential_version"]),
                    last_test_ok=None if test_ok_raw is None else bool(int(test_ok_raw)),
                    last_test_at=str(row["last_test_at"] or "") or None,
                    last_test_latency_ms=None if row["last_test_latency_ms"] is None else int(row["last_test_latency_ms"]),
                    last_error_code=str(row["last_error_code"] or "") or None,
                    last_error_category=str(row["last_error_category"] or "") or None,
                    updated_at=str(row["updated_at"] or ""),
                )
            )
        return out

    def list_credentials(self, tenant_id: str) -> list[ExchangeCredentialMetadata]:
        conn = self._connect()
        try:
            self._ensure_exchange_credentials_schema(conn)
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
            self._ensure_exchange_credentials_schema(conn)
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

    def get_active_credential(self, tenant_id: str, exchange: str) -> ActiveExchangeCredential:
        conn = self._connect()
        try:
            self._ensure_exchange_credentials_schema(conn)
            row = conn.execute(
                """
                SELECT id, tenant_id, exchange, label, api_key_encrypted, api_secret_encrypted,
                       passphrase_encrypted, status, version, updated_at
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

        return ActiveExchangeCredential(
            credential_id=int(row["id"]),
            tenant_id=str(row["tenant_id"]),
            exchange=str(row["exchange"]),
            label=str(row["label"]),
            api_key=decrypt_secret(str(row["api_key_encrypted"])),
            api_secret=decrypt_secret(str(row["api_secret_encrypted"])),
            passphrase=(
                decrypt_secret(str(row["passphrase_encrypted"])) if row["passphrase_encrypted"] else None
            ),
            status=str(row["status"]),
            version=int(row["version"]),
            updated_at=str(row["updated_at"]),
        )

    def get_credentials_by_id(self, tenant_id: str, credential_id: int) -> ExchangeCredentials:
        conn = self._connect()
        try:
            self._ensure_exchange_credentials_schema(conn)
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
            self._ensure_exchange_credentials_schema(conn)
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
            self._ensure_exchange_credentials_schema(conn)
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
            self._upsert_exchange_status(
                conn,
                tenant_id=tenant_id,
                exchange=str(exchange or "").lower(),
                label=label,
                status="ACTIVE",
                credential_id=credential_id,
                credential_version=1,
                updated_at=now_iso,
            )
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
            self._ensure_exchange_credentials_schema(conn)
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
            self._upsert_exchange_status(
                conn,
                tenant_id=tenant_id,
                exchange=str(row["exchange"] or "").lower(),
                label=new_label,
                status=new_status,
                credential_id=credential_id,
                credential_version=next_version,
                updated_at=now_iso,
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
            self._ensure_exchange_credentials_schema(conn)
            row = conn.execute(
                "SELECT version FROM exchange_credentials WHERE tenant_id = ? AND id = ? LIMIT 1",
                (tenant_id, credential_id),
            ).fetchone()
            if not row:
                raise CredentialsNotFoundError(f"Credential not found for tenant='{tenant_id}' id='{credential_id}'")
            next_version = int(row["version"]) + 1
            full_row = conn.execute(
                "SELECT exchange, label FROM exchange_credentials WHERE tenant_id = ? AND id = ? LIMIT 1",
                (tenant_id, credential_id),
            ).fetchone()
            conn.execute(
                """
                UPDATE exchange_credentials
                SET status = 'REVOKED', version = ?, updated_at = ?, updated_by = ?
                WHERE tenant_id = ? AND id = ?
                """,
                (next_version, now_iso, user_id, tenant_id, credential_id),
            )
            if full_row:
                self._upsert_exchange_status(
                    conn,
                    tenant_id=tenant_id,
                    exchange=str(full_row["exchange"] or "").lower(),
                    label=str(full_row["label"] or ""),
                    status="REVOKED",
                    credential_id=credential_id,
                    credential_version=next_version,
                    updated_at=now_iso,
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

        now_iso = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        conn = self._connect()
        try:
            self._ensure_exchange_credentials_schema(conn)
            self._ensure_exchange_status_schema(conn)
            row = conn.execute(
                """
                SELECT exchange, label, status, version
                FROM exchange_credentials
                WHERE tenant_id = ? AND id = ?
                LIMIT 1
                """,
                (tenant_id, credential_id),
            ).fetchone()
            if row:
                self._upsert_exchange_status(
                    conn,
                    tenant_id=tenant_id,
                    exchange=str(row["exchange"] or "").lower(),
                    label=str(row["label"] or ""),
                    status=str(row["status"] or "UNKNOWN").upper(),
                    credential_id=credential_id,
                    credential_version=int(row["version"]) if row["version"] is not None else None,
                    updated_at=now_iso,
                    last_test_ok=bool(ok),
                    last_test_at=now_iso,
                    last_test_latency_ms=None if latency_ms is None else int(latency_ms),
                    last_error_code=error_code,
                    last_error_category=category,
                )
                conn.commit()
        finally:
            conn.close()
