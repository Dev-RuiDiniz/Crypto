import os

import pytest

from security.crypto import CryptoConfigError, decrypt_secret, encrypt_secret


def test_encrypt_decrypt_roundtrip(monkeypatch):
    monkeypatch.setenv("EXCHANGE_CREDENTIALS_MASTER_KEY", "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef")
    original = "segredo-super-sensivel"
    encrypted = encrypt_secret(original)
    assert decrypt_secret(encrypted) == original


def test_encrypted_payload_format(monkeypatch):
    monkeypatch.setenv("EXCHANGE_CREDENTIALS_MASTER_KEY", "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef")
    encrypted = encrypt_secret("abc")
    parts = encrypted.split(":")
    assert len(parts) == 3
    assert all(parts)


def test_encrypt_fails_without_master_key(monkeypatch):
    monkeypatch.delenv("EXCHANGE_CREDENTIALS_MASTER_KEY", raising=False)
    with pytest.raises(CryptoConfigError):
        encrypt_secret("abc")
