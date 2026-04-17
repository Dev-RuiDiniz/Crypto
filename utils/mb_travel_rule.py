from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict

TRAVEL_RULE_EFFECTIVE_DATE = date(2026, 5, 1)
ALLOWED_CUSTODY_TYPES = {"SELF_CUSTODY", "NATIONAL_TRANSFER", "INTERNATIONAL_TRANSFER"}


def normalize_wallet_symbol(symbol: str) -> str:
    raw = str(symbol or "").strip().upper()
    if not raw:
        raise ValueError("wallet symbol is required")
    if "/" in raw:
        return raw.split("/", 1)[0].strip()
    if "-" in raw:
        return raw.split("-", 1)[0].strip()
    return raw


def is_crypto_wallet_symbol(symbol: str) -> bool:
    return normalize_wallet_symbol(symbol) != "BRL"


def travel_rule_is_effective(today: date | None = None, *, effective_date: date = TRAVEL_RULE_EFFECTIVE_DATE) -> bool:
    ref = today or datetime.now(timezone.utc).date()
    return ref >= effective_date


def normalize_withdraw_travel_rule(payload: Dict[str, Any]) -> Dict[str, Any]:
    return _normalize_travel_rule_payload(payload, allow_declared_client=False)


def normalize_deposit_travel_rule(payload: Dict[str, Any]) -> Dict[str, Any]:
    return _normalize_travel_rule_payload(payload, allow_declared_client=True)


def _normalize_travel_rule_payload(payload: Dict[str, Any], *, allow_declared_client: bool) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("travel_rule must be an object")

    custody_type = str(payload.get("custody_type") or "").strip().upper()
    counterparty_name = str(payload.get("counterparty_name") or "").strip()
    if custody_type not in ALLOWED_CUSTODY_TYPES:
        raise ValueError("travel_rule.custody_type must be SELF_CUSTODY, NATIONAL_TRANSFER or INTERNATIONAL_TRANSFER")
    if not counterparty_name:
        raise ValueError("travel_rule.counterparty_name is required")

    normalized: Dict[str, Any] = {
        "custody_type": custody_type,
        "counterparty_name": counterparty_name,
    }

    for key in ("counterparty_relationship_code", "counterparty_vasp", "purpose_code"):
        value = str(payload.get(key) or "").strip()
        if value:
            normalized[key] = value

    country = str(payload.get("counterparty_country") or "").strip().upper()
    if country:
        normalized["counterparty_country"] = country

    if custody_type == "INTERNATIONAL_TRANSFER":
        missing = [key for key in ("counterparty_country", "counterparty_vasp", "purpose_code") if key not in normalized]
        if missing:
            raise ValueError(f"travel_rule missing required fields for INTERNATIONAL_TRANSFER: {', '.join(missing)}")

    if allow_declared_client:
        for key in ("declared_client_name", "declared_client_city"):
            value = str(payload.get(key) or "").strip()
            if value:
                normalized[key] = value

    return normalized
