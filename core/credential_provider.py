from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from core.credentials_service import (
    ActiveExchangeCredential,
    ExchangeCredentialsService,
    CredentialsNotFoundError,
)

ALIASES = {
    "gate": "gateio",
    "gateio": "gate",
    "mexc3": "mexc",
    "mexc": "mexc3",
}


def _exchange_candidates(exchange: str) -> list[str]:
    low = str(exchange or "").strip().lower()
    if not low:
        return []
    out = [low]
    alias = ALIASES.get(low)
    if alias and alias not in out:
        out.append(alias)
    return out


@dataclass
class CredentialRecord:
    credential_id: int
    version: int
    api_key: str
    api_secret: str
    passphrase: Optional[str]
    status: str
    updated_at: str


class CredentialProvider:
    def __init__(self, service: ExchangeCredentialsService):
        self.service = service

    def get_active_credential(self, tenant_id: str, exchange: str) -> CredentialRecord:
        last_err: Exception | None = None
        cred: ActiveExchangeCredential | None = None
        for candidate in _exchange_candidates(exchange):
            try:
                cred = self.service.get_active_credential(tenant_id, candidate)
                break
            except CredentialsNotFoundError as exc:
                last_err = exc
                continue
        if cred is None:
            if last_err is not None:
                raise last_err
            raise CredentialsNotFoundError(
                f"No active credentials found for tenant='{tenant_id}' exchange='{exchange}'"
            )
        status = (cred.status or "").upper()
        if status != "ACTIVE":
            raise CredentialsNotFoundError(
                f"Credential for tenant='{tenant_id}' exchange='{exchange}' is not active (status={status})"
            )
        return CredentialRecord(
            credential_id=cred.credential_id,
            version=cred.version,
            api_key=cred.api_key,
            api_secret=cred.api_secret,
            passphrase=cred.passphrase,
            status=cred.status,
            updated_at=cred.updated_at,
        )
