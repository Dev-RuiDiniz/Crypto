from __future__ import annotations

import base64
import os
from typing import Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MASTER_KEY_ENV = "EXCHANGE_CREDENTIALS_MASTER_KEY"
_NONCE_SIZE = 12


class CryptoConfigError(RuntimeError):
    pass


def _load_master_key(raw_value: Optional[str] = None) -> bytes:
    raw = (raw_value if raw_value is not None else os.getenv(MASTER_KEY_ENV, "")).strip()
    if not raw:
        raise CryptoConfigError(f"Missing required env var: {MASTER_KEY_ENV}")

    # aceita hex (64 chars) ou base64/urlsafe base64 (32 bytes)
    try:
        if len(raw) == 64:
            key = bytes.fromhex(raw)
        else:
            key = base64.b64decode(raw)
    except Exception as exc:
        raise CryptoConfigError("Invalid master key format. Use 64-char hex or base64.") from exc

    if len(key) != 32:
        raise CryptoConfigError("Master key must decode to exactly 32 bytes (AES-256).")
    return key


def encrypt_secret(value: str, *, master_key: Optional[str] = None) -> str:
    plain = (value or "").encode("utf-8")
    key = _load_master_key(master_key)
    nonce = os.urandom(_NONCE_SIZE)
    aesgcm = AESGCM(key)
    encrypted = aesgcm.encrypt(nonce, plain, None)
    ciphertext, tag = encrypted[:-16], encrypted[-16:]
    payload = b":".join(
        [
            base64.b64encode(nonce),
            base64.b64encode(ciphertext),
            base64.b64encode(tag),
        ]
    )
    return payload.decode("ascii")


def decrypt_secret(payload: str, *, master_key: Optional[str] = None) -> str:
    key = _load_master_key(master_key)
    try:
        nonce_b64, ciphertext_b64, tag_b64 = payload.split(":", 2)
        nonce = base64.b64decode(nonce_b64)
        ciphertext = base64.b64decode(ciphertext_b64)
        tag = base64.b64decode(tag_b64)
    except Exception as exc:
        raise ValueError("Invalid encrypted payload format. Expected base64(nonce:ciphertext:tag)") from exc

    if len(nonce) != _NONCE_SIZE:
        raise ValueError("Invalid nonce size.")
    if len(tag) != 16:
        raise ValueError("Invalid tag size.")

    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(nonce, ciphertext + tag, None)
    return plaintext.decode("utf-8")
