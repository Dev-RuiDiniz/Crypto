# Sprint 1 — Auditoria inicial (pré-implementação)

## 1) Leitura atual de `config.txt`

## Existe
- `bot.py` carrega `config.txt` por `load_config()` e resolve path no `main()` usando `resolve_config_path(...)` antes do boot do worker.
- `exchanges/exchanges_client.py` usa credenciais de `[EXCHANGES.<nome>]` via `_build_auth_params()` (`API_KEY`, `API_SECRET`, `PASSWORD`) para instanciar CCXT.
- `exchanges/adapters.py` (`MBV4Adapter`) lê `MBV4_LOGIN`, `MBV4_PASSWORD`, `MBV4_BEARER_TOKEN` da seção `EXCHANGES.mercadobitcoin`.
- `app/launcher.py` também exige `config.txt` para iniciar worker/API (arquivo legado).

## Parcial
- API e runtime já usam SQLite (`GLOBAL.SQLITE_PATH`) e têm infra de estado/versão; porém não havia cofre de credenciais.

## Não existe
- Remoção completa da dependência de `config.txt` para credenciais de exchange no worker.

## 2) Multi-tenant, criptografia, migrations, auditoria

## Existe
- Persistência SQLite central em `core/state_store.py` com criação evolutiva de schema no boot.
- Logging estruturado básico em `utils/logger.py` e tabela `event_log` em `core/state_store.py`.

## Parcial
- Há noções de `updated_by` em `config_version`, mas sem tenant/user auth completo.

## Não existe
- Entidade `Tenant`.
- Tabela de cofre (`exchange_credentials`) com segredo criptografado.
- AES-256-GCM para segredo em repouso.
- `audit_logs` dedicado com metadata redigida.
- Contexto de tenant no worker (JWT/request context não aplicável no worker atual).

## 3) Decisões de implementação da Sprint 1

- **Reaproveitar** `core/state_store.py` como ponto único de “migrations locais” (CREATE TABLE IF NOT EXISTS + índices).
- **Reaproveitar** `utils/logger.py` para adicionar redaction global, em vez de criar novo stack de logging.
- **Criar do zero**:
  - `security/crypto.py` (AES-256-GCM + `EXCHANGE_CREDENTIALS_MASTER_KEY`)
  - `core/credentials_service.py` (cofre por `tenant_id + exchange`)
  - `core/audit_log_service.py` (gravação de auditoria com metadata sem segredos)
  - tabelas `tenants`, `exchange_credentials`, `audit_logs`.
- **Integração worker**: `ExchangeHub` passa a buscar credenciais no cofre e falhar explicitamente quando ausentes, sem fallback para `config.txt`.
