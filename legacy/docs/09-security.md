# 09 - Security

## Credenciais
- Armazenadas criptografadas em SQLite (`exchange_credentials`).
- Criptografia AES-256-GCM (`security/crypto.py`).
- Chave mestra via env var (`EXCHANGE_CREDENTIALS_MASTER_KEY`).

## Boas práticas
- Nunca commitar segredos em `config.txt`/`.env`.
- Usar permissões de API key **trade-only** (sem saque).
- Redigir logs sensíveis (já há redaction no projeto).

## Gap
- Remover uso legado de credenciais em INI para produção e forçar vault.
