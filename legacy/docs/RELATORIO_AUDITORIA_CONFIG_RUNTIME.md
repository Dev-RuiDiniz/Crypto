# RELATÓRIO DE AUDITORIA — Configuração Runtime vs README

## 1) Resumo executivo
Esta auditoria confirmou que o repositório **possui backend para `config_pairs`** (GET/POST em `/api/bot-config`) e o worker efetivamente recarrega `risk_percentage` em runtime com cache TTL. Porém, a evidência do frontend mostra que o dashboard atual **não implementa UI de CRUD de `config_pairs`**: ele edita apenas `config.txt` via `/api/config`.

O modo multi-pair existe (loop por pares no mesmo ciclo), mas o isolamento de falha está **parcial**: há tolerância para falha por exchange em coleta de mids, porém não há `try/except` por par no loop principal. Assim, uma exceção em um par pode interromper o restante dos pares daquele ciclo.

O risco de inconsistência de `SQLITE_PATH` entre API e worker é real em cenários com processos/working dirs divergentes ou múltiplos arquivos de config/banco. Há mitigação parcial porque a API resolve caminho absoluto a partir de `PROJECT_ROOT`, mas não há handshake de consistência entre processos.

Conclusão geral: as capacidades centrais existem, mas há divergências entre promessa de “dashboard de configuração por par” e o que o frontend realmente entrega hoje.

---

## 2) Tabela de status (pontos 1–4)

| Ponto | Status | Conclusão curta |
|---|---|---|
| 1) Dashboard edita `config_pairs` via UI | **Parcial** | Backend pronto (`/api/bot-config`), mas frontend não consome esse endpoint. |
| 2) Multi-pair simultâneo + isolamento por par | **Parcial** | Multi-pair implementado; isolamento de erro é global por ciclo, não por par. |
| 3) Reload dinâmico de `risk_percentage` sem restart | **Implementado** (com ressalva de TTL) | Worker recarrega por TTL e aplica no sizing no `OrderRouter`. |
| 4) Inconsistência de `SQLITE_PATH` API vs worker | **Risco real: Sim** | É possível API escrever em DB A e worker ler DB B sem detecção automática. |

---

## 3) Detalhamento por ponto

## 3.1) Dashboard edita `config_pairs` via UI ou só API?

### Conclusão
**Parcial**: existe API para CRUD/upsert de `config_pairs`, porém não há evidência de tela/fluxo no frontend usando `/api/bot-config`.

### Evidências no código
- Rotas API expostas:
  - `GET/POST /api/bot-config` em `api/server.py`.
  - Handlers de leitura e upsert em `api/handlers.py` (`get_bot_configs`, `upsert_bot_config`).
- Frontend atual:
  - `frontend/src/utils/api.js` chama apenas `/api/config` para configuração.
  - Não há chamadas para `/api/bot-config` em `frontend/src/*`.
  - `frontend/src/components/Config.js` manipula grupos de `config.txt` (global/boot/router/risk/pairs/log), não CRUD da tabela `config_pairs`.

### Mapa de rotas do dashboard/API
- Front: `/` + arquivos de `frontend/src` servidos por Flask.
- API observabilidade/config geral: `/api/ping`, `/api/balances`, `/api/orders`, `/api/mids`, `/api/config`, `/api/events`, `/api/debug`.
- API bot_config por par: `/api/bot-config` (GET/POST).

### Risco/impacto
- Usuário pode acreditar que “dashboard configura por par” via interface, mas na prática precisará usar curl/Postman/cliente externo para `risk_percentage` por par.

### Ação recomendada (mínima)
- Implementar no frontend uma aba “Config por Par” consumindo:
  - `GET /api/bot-config` (listagem),
  - `POST /api/bot-config` (upsert).
- Enquanto não houver UI, documentar claramente: “edição de `config_pairs` é via API/DB”.

---

## 3.2) Multi-pair simultâneo + isolamento por par

### Conclusão
**Parcial**: loop multi-pair existe no mesmo ciclo, mas isolamento de erro por par é incompleto.

### Evidências no código
- Multi-pair no mesmo ciclo:
  - `MainMonitor.run()` faz `for pair in self.pairs` no loop principal.
  - `self.pairs` combina pares de `[PAIRS].LIST` e `config_pairs` via `_refresh_pairs_from_db()`.
- Isolamento parcial:
  - Coleta de mids usa `asyncio.gather(..., return_exceptions=True)` por exchange, evitando quebra total na coleta daquele par.
  - Porém o `try/except` que protege processamento está em bloco amplo envolvendo o `for pair in self.pairs`, não por iteração. Exceção em um par pode pular os demais pares do ciclo atual.
- Timeouts:
  - Nesta camada (monitor/router) não há timeout explícito por par no loop; depende das camadas de exchange/HTTP.

### Pseudofluxo real
1. `while True` do monitor.
2. `_refresh_pairs_from_db()` (respeitando TTL).
3. `for pair in self.pairs`:
   - `_load_pair_config(pair, now)`
   - `_mid_per_exchange(pair)`
   - `strategy.targets_for(...)`
   - `router.reprice_pair(..., risk_percentage=cfg_risk, ...)`
4. render/publish snapshot/poll fills/sleep.

### Risco/impacto
- Falha em um único par (exceção não tratada) pode atrasar ou impedir processamento dos demais pares no ciclo em execução.
- Latência elevada em chamadas de um par tende a alongar o ciclo todo (processamento serial por par).

### Ação recomendada (mínima)
- Envolver cada iteração de par com `try/except` dedicado:
  - log com contexto do par,
  - `continue` para preservar os demais pares.
- Opcional P1: timeout por par (ex.: `asyncio.wait_for`) para limites de latência.

---

## 3.3) Reload dinâmico de `risk_percentage` em runtime

### Conclusão
**Implementado**, com comportamento condicionado ao TTL (`BOT_CONFIG_CACHE_TTL_SEC`).

### Evidências no código
- Persistência/edição:
  - `POST /api/bot-config` grava em `config_pairs` (`upsert_bot_config`).
- Recarregamento no worker:
  - `MainMonitor` lê `BOT_CONFIG_CACHE_TTL_SEC`.
  - `_load_pair_config()` mantém cache por par com timestamp (`self._bot_config_cache_ts`).
  - após expirar TTL, lê novamente `state.get_bot_configs()`.
- Aplicação do valor:
  - `run()` passa `cfg_risk` para `router.reprice_pair(... risk_percentage=cfg_risk ...)`.
  - `OrderRouter._calc_amount()` usa `risk_percentage` para limitar notional/qty (modos `FIXO_USDT` e percentual).
  - `OrderRouter` loga `[position_sizing] ... risk_percentage=...` e grava em `paper_orders` via `_record_paper_execution`.

### Fluxo completo (edição → execução)
1. Cliente envia `POST /api/bot-config` com `pair` e `risk_percentage`.
2. API faz upsert em `config_pairs` no SQLite.
3. Worker, no próximo ciclo em que TTL expirar, recarrega config do par.
4. `cfg_risk` atualizado entra em `reprice_pair`.
5. `_calc_amount` aplica o novo % no sizing, afetando qty/notional da ordem.

### Risco/impacto
- Mudança não é instantânea em milissegundos: respeita TTL do cache.
- Se API e worker estiverem em bancos diferentes (ponto 4), atualização pode nunca refletir no worker.

### Ação recomendada (mínima)
- Documentar SLA de propagação: “até `BOT_CONFIG_CACHE_TTL_SEC` + duração do ciclo”.
- Opcional: endpoint/flag para invalidação de cache no worker.

---

## 3.4) Inconsistência de `SQLITE_PATH` entre worker e API

### Conclusão
**Risco real: Sim**.

### Evidências no código
- Worker:
  - `StateStore` usa `cfg.get("GLOBAL", "SQLITE_PATH", fallback="./data/state.db")`.
  - Path relativo é resolvido pelo processo/shell atual (não há normalização explícita para root fixo).
- API:
  - `_resolve_sqlite_path` em `api/handlers.py` lê `SQLITE_PATH` de `config.txt` e converte relativo para absoluto usando `PROJECT_ROOT`.
- Não há validação cruzada API↔worker informando divergência de DB ativo.

### Cenários de falha
1. API grava em DB A (resolvido por `PROJECT_ROOT`), worker lê DB B (path relativo em outro CWD/config).
2. Usuário altera `risk_percentage` via API e não vê efeito no worker.
3. Dashboard exibe dados de um banco diferente da execução real.

### Risco/impacto
- Inconsistência operacional grave: decisões de risco e habilitação de pares podem divergir do que o operador enxerga.

### Ação recomendada (mínima)
- P0: normalizar resolução de path no worker igual à API (absoluto via raiz canônica).
- P0: logar no startup (API e worker) o caminho absoluto do DB efetivo.
- P1: endpoint health de consistência (API informa DB path; worker também; comparar).
- P1: em Docker, usar volume único e env var compartilhada para `SQLITE_PATH`.

---

## 4) Lista de arquivos e trechos-chave
- `README.md` — promessas de multi-pair, reload de `risk_percentage`, dashboard/config, alerta sobre `SQLITE_PATH`.
- `api/server.py` — rotas `/api/config` e `/api/bot-config`.
- `api/handlers.py` — resolução de `SQLITE_PATH`, CRUD de `config_pairs`.
- `frontend/src/utils/api.js` — chamadas atuais do frontend (sem `/api/bot-config`).
- `frontend/src/components/Config.js` — UI de config INI (`/api/config`), sem CRUD por par em DB.
- `core/monitors.py` — loop principal por par, refresh de pares/config por TTL.
- `core/order_router.py` — aplicação de `risk_percentage` no cálculo de sizing.
- `core/state_store.py` — schema `config_pairs` e leitura de bot_config.

---

## 5) Riscos para o cliente e por que “pareceu não funcionar”
1. **Expectativa de UI para `config_pairs`**: cliente abriu dashboard e não encontrou CRUD por par.
2. **Atualização “não imediata”**: valor muda somente após expiração de TTL + próximo ciclo.
3. **Banco divergente**: API atualiza um SQLite e worker lê outro.
4. **Falha em um par impactando ciclo**: sem `try/except` por par, erro pode interromper o restante no ciclo.

---

## 6) Próximos passos priorizados (P0/P1/P2)

### P0 (alta prioridade)
- Implementar `try/except` por par no loop principal para isolamento robusto.
- Exibir/logar caminho absoluto do SQLite em API e worker e padronizar resolução.
- Ajustar documentação para deixar explícito que `config_pairs` hoje é via API/DB (não via UI).

### P1
- Criar UI de gestão de `config_pairs` no dashboard.
- Criar endpoint/telemetria de “último reload de bot_config” e “DB path ativo do worker”.
- Adicionar timeout por par (ou por bloco de coleta/reprice).

### P2
- Considerar estratégia de execução concorrente por par (com controle de backpressure).
- Melhorar observabilidade de latência por par/exchange.
