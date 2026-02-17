from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Optional, Set

from flask import Request


@dataclass
class AuthContext:
    user_id: str
    tenant_id: str
    roles: Set[str]


def _decode_bearer_payload(token: str) -> dict:
    parts = token.split('.')
    if len(parts) < 2:
        return {}
    payload_b64 = parts[1]
    payload_b64 += '=' * (-len(payload_b64) % 4)
    try:
        raw = base64.urlsafe_b64decode(payload_b64.encode('utf-8'))
        return json.loads(raw.decode('utf-8'))
    except Exception:
        return {}


def extract_auth_context(request: Request) -> Optional[AuthContext]:
    auth_header = (request.headers.get('Authorization') or '').strip()
    payload: dict = {}
    if auth_header.lower().startswith('bearer '):
        payload = _decode_bearer_payload(auth_header.split(' ', 1)[1].strip())

    user_id = str(
        payload.get('sub')
        or payload.get('userId')
        or request.headers.get('X-User-Id', '')
    ).strip()
    tenant_id = str(
        payload.get('tenantId')
        or payload.get('tenant_id')
        or request.headers.get('X-Tenant-Id', '')
    ).strip()

    raw_roles = payload.get('roles') or request.headers.get('X-Roles', '')
    roles: Set[str] = set()
    if isinstance(raw_roles, list):
        roles = {str(r).strip().upper() for r in raw_roles if str(r).strip()}
    else:
        roles = {chunk.strip().upper() for chunk in str(raw_roles).split(',') if chunk.strip()}

    if not user_id or not tenant_id:
        return None
    return AuthContext(user_id=user_id, tenant_id=tenant_id, roles=roles)
