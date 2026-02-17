from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

import ccxt.async_support as ccxt
from ccxt.base.errors import AuthenticationError

from core.credential_provider import CredentialProvider, CredentialRecord
from core.credentials_service import ExchangeCredentialsService
from core.notification_service import NotificationEventType, NotificationSeverity
from utils.logger import get_logger

log = get_logger("exchange_client_manager")

ALIASES_CCXT = {
    "gateio": "gate",
    "mexc3": "mexc",
}


def _ccxt_id_candidates(ex_name: str) -> list[str]:
    if ex_name.lower() == "mercadobitcoin":
        return ["mercadobitcoin", "mercado"]
    low = ex_name.lower()
    return [ALIASES_CCXT.get(low, low)]


@dataclass
class ClientCacheEntry:
    client: Any
    credential_id: int
    version: int
    created_at: float
    last_used_at: float
    state: str
    paused: bool = False
    pause_reason: str = ""


class ExchangeClientFactory:
    def __init__(self, http_timeout_sec: int):
        self.http_timeout_sec = int(http_timeout_sec)

    async def create(self, exchange: str, credentials: CredentialRecord) -> ccxt.Exchange:
        last_exc = None
        for candidate in _ccxt_id_candidates(exchange):
            if not hasattr(ccxt, candidate):
                continue
            try:
                ex_cls = getattr(ccxt, candidate)
                ex = ex_cls(
                    {
                        "apiKey": credentials.api_key,
                        "secret": credentials.api_secret,
                        "password": credentials.passphrase,
                        "enableRateLimit": True,
                        "timeout": self.http_timeout_sec * 1000,
                        "options": {"defaultType": "spot", "recvWindow": 60_000},
                    }
                )
                return ex
            except Exception as exc:
                last_exc = exc
                continue
        if last_exc:
            raise last_exc
        raise RuntimeError(f"unsupported exchange: {exchange}")


class AuthErrorClassifier:
    @staticmethod
    def is_auth_error(err: Exception) -> tuple[bool, str]:
        if isinstance(err, AuthenticationError):
            return True, "AUTHENTICATION_ERROR"

        msg = str(err).lower()
        checks = {
            "invalid api": "INVALID_API_KEY",
            "signature": "SIGNATURE_ERROR",
            "permission": "PERMISSION_DENIED",
            "forbidden": "PERMISSION_DENIED",
            "recvwindow": "TIMESTAMP_WINDOW",
            "timestamp": "TIMESTAMP_WINDOW",
            "api-key": "INVALID_API_KEY",
            "auth": "AUTHENTICATION_ERROR",
        }
        for key, category in checks.items():
            if key in msg:
                return True, category
        return False, ""


class ExchangeClientManager:
    def __init__(
        self,
        tenant_id: str,
        provider: CredentialProvider,
        service: ExchangeCredentialsService,
        factory: ExchangeClientFactory,
        notification_service=None,
    ):
        self.tenant_id = tenant_id
        self.provider = provider
        self.service = service
        self.factory = factory
        self.notification_service = notification_service
        self.cache: Dict[str, ClientCacheEntry] = {}
        self.rotation_locks: Dict[str, asyncio.Lock] = {}
        self.operation_locks: Dict[str, asyncio.Lock] = {}

    def _key(self, exchange: str) -> str:
        return f"{self.tenant_id}:{exchange.lower()}"

    def _rotation_lock(self, key: str) -> asyncio.Lock:
        if key not in self.rotation_locks:
            self.rotation_locks[key] = asyncio.Lock()
        return self.rotation_locks[key]

    def _operation_lock(self, key: str) -> asyncio.Lock:
        if key not in self.operation_locks:
            self.operation_locks[key] = asyncio.Lock()
        return self.operation_locks[key]

    async def ensure_client(self, exchange: str, correlation_id: str = "") -> ClientCacheEntry:
        key = self._key(exchange)
        cred = self.provider.get_active_credential(self.tenant_id, exchange)
        current = self.cache.get(key)
        now = time.time()

        if current and current.paused and cred.version == current.version:
            raise RuntimeError(f"exchange paused due to invalid credentials: {exchange}")

        if current and current.version == cred.version and current.state == "READY":
            current.last_used_at = now
            log.info("CLIENT_CACHE_HIT tenantId=%s exchange=%s credentialId=%s version=%s", self.tenant_id, exchange, current.credential_id, current.version)
            return current

        log.info("CLIENT_CACHE_MISS tenantId=%s exchange=%s", self.tenant_id, exchange)
        lock = self._rotation_lock(key)
        async with lock:
            cred_check = self.provider.get_active_credential(self.tenant_id, exchange)
            latest = self.cache.get(key)
            if latest and latest.version == cred_check.version and latest.state == "READY":
                latest.last_used_at = now
                return latest

            if latest:
                log.info(
                    "EXCHANGE_CLIENT_ROTATION_DETECTED tenantId=%s exchange=%s credentialId=%s oldVersion=%s newVersion=%s correlationId=%s",
                    self.tenant_id,
                    exchange,
                    cred_check.credential_id,
                    latest.version,
                    cred_check.version,
                    correlation_id,
                )

            rotated = await self._rotate_client(exchange, cred_check, correlation_id=correlation_id)
            return rotated

    async def _rotate_client(self, exchange: str, cred: CredentialRecord, correlation_id: str = "") -> ClientCacheEntry:
        key = self._key(exchange)
        old = self.cache.get(key)
        rotation_id = f"rot-{int(time.time() * 1000)}"
        if old:
            old.state = "ROTATING"

        try:
            client = await self.factory.create(exchange.lower(), cred)
            new_entry = ClientCacheEntry(
                client=client,
                credential_id=cred.credential_id,
                version=cred.version,
                created_at=time.time(),
                last_used_at=time.time(),
                state="READY",
                paused=False,
            )
            self.cache[key] = new_entry
            if old and old.client:
                try:
                    await old.client.close()
                except Exception:
                    pass
            log.info(
                "EXCHANGE_CLIENT_ROTATED tenantId=%s exchange=%s credentialId=%s oldVersion=%s newVersion=%s rotationId=%s correlationId=%s",
                self.tenant_id,
                exchange,
                cred.credential_id,
                old.version if old else None,
                cred.version,
                rotation_id,
                correlation_id,
            )
            return new_entry
        except Exception as exc:
            if old:
                old.state = "FAILED"
            log.error(
                "EXCHANGE_CLIENT_ROTATION_FAILED tenantId=%s exchange=%s credentialId=%s version=%s rotationId=%s error=%s",
                self.tenant_id,
                exchange,
                cred.credential_id,
                cred.version,
                rotation_id,
                exc,
            )
            raise

    async def run_with_operation_lock(self, exchange: str, fn):
        key = self._key(exchange)
        lock = self._operation_lock(key)
        async with lock:
            entry = await self.ensure_client(exchange)
            if entry.state == "ROTATING":
                raise RuntimeError(f"Client rotating for {exchange}")
            return await fn(entry.client)

    async def mark_auth_failed_and_pause(self, exchange: str, err: Exception):
        key = self._key(exchange)
        entry = self.cache.get(key)
        if not entry:
            return

        auth, category = AuthErrorClassifier.is_auth_error(err)
        if not auth:
            return

        entry.paused = True
        entry.state = "FAILED"
        entry.pause_reason = category
        try:
            self.service.update_credentials(
                self.tenant_id,
                entry.credential_id,
                label=None,
                status="INACTIVE",
                api_key=None,
                api_secret=None,
                passphrase=None,
                user_id="worker",
            )
        except Exception as update_exc:
            log.error("failed to mark credential inactive tenantId=%s exchange=%s credentialId=%s err=%s", self.tenant_id, exchange, entry.credential_id, update_exc)

        log.error(
            "EXCHANGE_AUTH_FAILED_PAUSED tenantId=%s exchange=%s credentialId=%s version=%s category=%s ALERT_AUTH_FAILED",
            self.tenant_id,
            exchange,
            entry.credential_id,
            entry.version,
            category,
        )
        if self.notification_service is not None:
            self.notification_service.notify_nowait(
                tenant_id=self.tenant_id,
                event_type=NotificationEventType.AUTH_FAILED,
                severity=NotificationSeverity.ERROR,
                payload={
                    "symbol": "-",
                    "exchange": exchange,
                    "amount": 0,
                    "price": 0,
                    "reason": category,
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                },
            )

    def mark_resumed_if_applicable(self, exchange: str):
        key = self._key(exchange)
        entry = self.cache.get(key)
        if not entry or not entry.paused:
            return
        entry.paused = False
        entry.state = "READY"
        log.info(
            "EXCHANGE_RESUMED tenantId=%s exchange=%s credentialId=%s version=%s",
            self.tenant_id,
            exchange,
            entry.credential_id,
            entry.version,
        )
