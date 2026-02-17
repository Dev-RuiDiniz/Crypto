# Auditoria e Consolidação do Projeto — Robô de Trading Cripto (Spot)

## Resumo executivo
**Veredito geral:** **PARCIAL**.

O repositório já possui base funcional sólida para bot spot multipar com API Flask, dashboard web e persistência em SQLite. Há suporte a modo PAPER e LIVE, gerenciamento dinâmico de configuração por DB (com `config_version`), adapters para exchanges (incluindo Mercado Bitcoin v4), controle básico de risco e cofre de credenciais com criptografia AES-GCM. Ainda assim, faltam pontos críticos para aderência total ao briefing: order book em *streaming* real (hoje é polling via CCXT), arbitragem simples internacional explicitamente implementada como estratégia dedicada, idempotência robusta de ordens com `clientOrderId`, e reforços operacionais de resiliência (ex.: circuit breaker). 

---

## 1) Auditoria completa do repositório

### 1.1 Mapeamento de arquitetura

| Camada | Componentes | Responsabilidade atual |
|---|---|---|
| Worker / Engine / Strategy | `bot.py`, `core/monitors.py`, `core/strategy_spread.py`, `core/order_router.py`, `core/order_manager.py` | Ciclo principal, cálculo de targets por spread, roteamento e manutenção de ordens por par/exchange. |
| Exchange adapters / clients | `exchanges/exchanges_client.py`, `exchanges/adapters.py`, `core/exchange_client_manager.py` | Abstração de exchanges via CCXT + adapter MB v4, retries, normalização de símbolos/preços, pause em falha auth. |
| Scheduler / Jobs | Loop assíncrono em `MainMonitor.run()` (ciclo por intervalo), bootstrap em `run_arbit.py` | Orquestra periodicidade de coleta/reprice/cancelamento sem scheduler externo dedicado. |
| Config / Secrets / Credentials | `config.txt`, `config.template.txt`, `.env.example`, `core/credentials_service.py`, `security/crypto.py` | Config INI + cofre em SQLite com criptografia AES-256-GCM para segredos. |
| Storage / DB | `core/state_store.py`, `data/state.db`, tabelas `orders`, `fills`, `config_pairs`, `bot_global_config`, `exchange_credentials` | Persistência de runtime, configurações de par/global e cofre de credenciais. |
| API backend | `api/server.py`, `api/handlers.py`, `api/exchange_credentials_api.py` | Endpoints de health, runtime/config, bot-config, credenciais, status worker. |
| Dashboard frontend | `frontend/src/App.js`, `frontend/src/components/*.js` | UI para status (balances/orders/mids) e configuração (pares, spreads, risco, credenciais). |
| Observabilidade | `utils/logger.py`, logs em `logs/`, endpoints `/api/health*` | Logging com redaction e deduplicação, health checks e config-status. |

### 1.1.1 Diagrama textual (fluxo principal)

```text
[config.txt + DB config_pairs/bot_global_config + exchange_credentials]
                |
                v
          [bot.py bootstrap]
                |
                v
       [MainMonitor loop job]
                |
    +-----------+------------+
    |                        |
    v                        v
[StrategySpread]      [OrderRouter/OrderManager]
    |                        |
    +-------------> [ExchangeHub + MBV4Adapter/CCXT]
                              |
                              v
                    [StateStore SQLite + CSV + snapshot]
                              |
                              v
                     [API Flask (handlers/shared_state)]
                              |
                              v
                        [Dashboard Web]
```

### 1.2 Inventário de pontos críticos

- **Entrada de configuração de pares e %**: via `config.txt` (`[PAIRS]`, `[SPREAD]`, `[RISK]`) e também via DB (`config_pairs`, `bot_global_config`) exposta por API (`/api/bot-config`, `/api/bot-global-config`).
- **Criação/cancelamento de ordens**: central em `OrderManager.ensure_orders()` e `ExchangeHub.create_limit_order()/cancel_order()`.
- **Leitura de order book**: via polling CCXT `fetch_order_book` em `ExchangeHub.get_orderbook()` (não há websocket nativo ativo no fluxo principal).
- **Cálculo de risco**: limites por par/lado/exchange em `RiskManager` + checks do router (min notional, exposição, max ordens).
- **Logs/erros**: `utils/logger.py` (formatação, dedupe, redaction), uso extensivo de `log.warning/error` em core/exchanges/api.
- **Chaves/credenciais**: armazenamento principal em tabela `exchange_credentials` (campos criptografados) via `ExchangeCredentialsService`; chave mestra por env `EXCHANGE_CREDENTIALS_MASTER_KEY`.

### 1.3 Evidências (arquivos, classes/funções, resumo)

- `bot.py` — `load_config`, `get_components`, bootstrap do worker e dependências críticas.
- `core/monitors.py` — `MainMonitor` executa loop principal e publica snapshot para API/dashboard.
- `core/strategy_spread.py` — `StrategySpread.compute_targets` calcula referência e preços alvo por spread.
- `core/order_router.py` — `reprice_pair` (fluxo de manutenção) e lógica de stake/spread por par.
- `core/order_manager.py` — `ensure_orders`, `_create_quantized`, `_cancel` para lifecycle de ordens.
- `exchanges/exchanges_client.py` — `ExchangeHub.get_orderbook`, `create_limit_order`, `cancel_order`, `probe_mid_usdt`.
- `core/risk_manager.py` — checagens de exposição, limite de ordens e kill switch por drawdown.
- `core/state_store.py` — schema SQLite (`config_pairs`, `orders`, `fills`, `exchange_credentials`, `config_version`).
- `api/server.py` + `api/handlers.py` — endpoints de health/config/status e persistência de config operacional.
- `api/exchange_credentials_api.py` + `core/credentials_service.py` + `security/crypto.py` — CRUD de credenciais com criptografia e RBAC básico por headers.
- `frontend/src/components/Config.js` e `ExchangesSettings.js` — UI para pares/risco/config geral e gestão de credenciais sem exibir segredo completo.

---

## 2) Matriz de aderência ao briefing

| Requisito do Briefing | Status | Evidências no código | O que falta exatamente |
|---|---|---|---|
| 1. Acompanhar order book em tempo real de vários pares | PARCIAL | `ExchangeHub.get_orderbook()` + chamadas por par/exchange no router/strategy. | Hoje é polling periódico; falta streaming websocket/assinatura contínua por livro. |
| 2. Ajustar ordens automaticamente por % do usuário | OK | `[SPREAD]` por par em `StrategySpread` e `OrderRouter._pair_spreads`. | — |
| 3. Cancelar e reinserir ordens conforme mercado | OK | `OrderManager.ensure_orders()` decide move/cancel/recreate; `ExchangeHub.cancel_order`. | Robustecer dedupe/idempotência externa. |
| 4. Comparar preços com mercados internacionais para arbitragem simples | PARCIAL | `StrategySpread` usa mids multi-exchange para preço de referência (`MEDIAN/VWAP`). | Falta módulo explícito de arbitragem (detectar spread intermarket e executar perna A/B). |
| 5. Interface web para pares, %/risco/saldo e status | OK | API `/api/config`, `/api/bot-config`; frontend `Config.js`, `Dashboard.js`, `ExchangesSettings.js`. | UX pode evoluir, mas requisito base atendido. |
| 6. Gestão de risco (parte do saldo e máximo por operação) | PARCIAL | `RiskManager`, stake por par `[STAKE]`, limites de exposição e ordens. | Falta limite financeiro “por operação” explícito e validado em toda criação de ordem com idempotência forte. |
| 7. Alertas por e-mail ou WhatsApp (opcional) | NÃO | Há eventos/logs no painel (`/api/events`), sem integração email/WhatsApp. | Implementar canal externo opcional (SMTP/WhatsApp API). |
| Multi-pair simultâneo | OK | Lista em `[PAIRS]`, loops por `self.pairs`, teste `test_paper_multipair.py`. | — |
| Atualização dinâmica de %/risco sem restart | OK | `config_version` + reload em monitor + API de bot config. | — |
| Segurança de credenciais (não no front; criptografado em repouso) | PARCIAL | Criptografia AES-GCM e API retorna metadados (`last4`). | `config.txt` ainda aceita campos legados de chaves; falta hardening para bloquear uso de segredo em arquivo no modo produção. |
| Idempotência/duplicidade de ordens | PARCIAL | Hash TTL em router e controle de ordem viva em `OrderManager`. | Falta `clientOrderId`/chave idempotente persistente por ordem e dedupe transacional. |
| Paper Trading vs Live | OK | `GLOBAL.MODE` + branches PAPER em create/cancel e tabela `paper_orders`. | — |

---

## 3) Consolidação de documentação

A estrutura obrigatória foi consolidada em `/docs` com visão funcional, setup, arquitetura, operação e segurança:

- `docs/00-overview.md`
- `docs/01-setup.md`
- `docs/02-architecture.md`
- `docs/03-configuration.md`
- `docs/04-exchanges.md`
- `docs/05-strategies.md`
- `docs/06-risk-management.md`
- `docs/07-operations-runbook.md`
- `docs/08-troubleshooting.md`
- `docs/09-security.md`
- `docs/10-api.md`
- `docs/11-dashboard.md`
- `docs/12-paper-vs-live.md`

README principal atualizado para refletir estado real atual e apontar para essa trilha.

---

## 4) Checagens de segurança e qualidade

### 4.1 Credenciais

- **Segredos em arquivos:** `config.txt` e `config.template.txt` possuem campos de credenciais, porém sem valores no estado atual do repositório.
- **Criptografia em repouso:** implementada (`security/crypto.py`) e usada em `core/credentials_service.py` para `api_key/api_secret/passphrase`.
- **Exposição no front:** frontend usa CRUD de credenciais por metadados (`last4`) e inputs de segredo apenas para envio; não renderiza segredo completo.
- **Redaction em logs:** `security/redaction.py` e filtro `RedactSecretsFilter` no logger.

### 4.2 Confiabilidade operacional

- **Retry/backoff:** tenacity com `stop_after_attempt` + `wait_exponential_jitter` no `ExchangeHub`.
- **Rate limit handling:** uso de `enableRateLimit` em clientes CCXT e endpoint rate limit no módulo de credenciais.
- **Falha de rede/timeouts:** tratamento de exceções (`NetworkError`, `RequestTimeout`) + timeout configurável.
- **Pausa por falha auth:** `ExchangeClientManager.mark_auth_failed_and_pause` acionado após falha em operações privadas.
- **Circuit breaker:** não identificado.
- **Idempotência forte:** parcial (controle local/hashes), sem `clientOrderId` persistente.

### 4.3 Testes

- **Unit/integration presentes** em `tests/`: segurança crypto, API de credenciais, runtime/health, multipair paper, pathing/config.
- **Lacunas mínimas para MVP confiável:**
  1. teste de integração live-like com mock de exchange para cancel/recreate em alta volatilidade;
  2. testes de idempotência transacional e reprocessamento pós-crash;
  3. testes de arbitragem (quando implementada);
  4. testes de carga para polling multipar/exchange.

---

## 5) Veredito final — “Falta alguma coisa?”

1. **O projeto atende ao briefing?**
   - **Parcialmente.**

2. **O que falta (priorizado por impacto/risco)**
   1. Estratégia explícita de arbitragem simples inter-exchange (alto impacto, alto risco).
   2. Streaming real de order book por websocket (alto impacto, médio/alto risco).
   3. Idempotência robusta com `clientOrderId` persistente + dedupe transacional (alto impacto, alto risco).
   4. Circuit breaker e políticas operacionais de degradação (médio impacto, médio risco).
   5. Alertas externos (email/WhatsApp) opcionais (médio impacto, baixo/médio risco).

3. **Roadmap sugerido (sprints)**
   - **Sprint 1 (base de execução segura):** idempotência de ordens + hardening de retries/timeouts + pausa/retomada operacional.
   - **Sprint 2 (dados de mercado em tempo real):** camada websocket order book/ticker com fallback polling.
   - **Sprint 3 (arbitragem simples MVP):** detector de oportunidade + execução controlada com limites.
   - **Sprint 4 (operação e alertas):** notificações externas, métricas e playbooks automáticos de incidentes.

4. **Riscos e dívidas técnicas que podem quebrar em produção**
   - Dependência de polling em mercado volátil pode causar slippage e churn de cancel/recreate.
   - Ausência de idempotência forte pode gerar ordem duplicada em retries/restarts.
   - Circuit breaker inexistente aumenta risco em falhas sistêmicas de exchange/rede.

5. **Estimativa de esforço relativa por lacuna**
   - Idempotência forte de ordens: **M**
   - Streaming websocket multipar/multiexchange: **G**
   - Estratégia arbitragem simples e execução segura: **G**
   - Alertas externos: **P**
   - Circuit breaker e políticas de fail-safe: **M**

---

## 6) Alterações realizadas nesta consolidação

- Criado `AUDITORIA_PROJETO.md` na raiz com auditoria completa, matriz de aderência e roadmap.
- README principal reescrito para refletir estado real atual, sem promessas fora do que existe.
- Estrutura documental padronizada em `/docs/00..12` com setup, arquitetura, configuração, segurança, operação, API e dashboard.
