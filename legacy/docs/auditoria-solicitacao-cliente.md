# Auditoria — Solicitação do Cliente (Multi-pair + risco dinâmico)

## Resumo executivo

Situação atual após auditoria:
- **Multi-pair simultâneo:** ✅ Implementado no worker (loop por pares, isolamento lógico por par/exchange).
- **Atualização dinâmica de `risk_percentage` sem restart:** ✅ Implementado no worker (reload por ciclo + cache TTL curto), com ajuste adicional nesta auditoria para facilitar operação via API (`/api/bot-config`) e observabilidade de sizing.

---

## Checklist (Existe x Falta)

## A) Multi-pair
- [x] Estrutura de config por par (`config_pairs` com `enabled`, `strategy`, `risk_percentage`, `max_daily_loss`, `updated_at`)
- [x] Scheduler/loop por par
- [x] Execution engine com símbolo/par dinâmico
- [x] Persistência de ordens/execuções por par
- [⚠] Dashboard sem tela dedicada de CRUD por par (há API)

## B) Atualização de % sem restart
- [x] `%` armazenada de forma persistente (SQLite)
- [x] Worker recarrega config em runtime
- [x] `%` usada no sizing real
- [x] Logs mínimos para auditoria de sizing (`pair`, `risk_percentage`, saldo usado, `qty`, `notional`)

---

## Evidências por item

## A1) Estrutura de config por par
- Tabela `config_pairs` criada com colunas necessárias e migração mínima para DB existente.
- Leitura normalizada via `get_bot_configs`.

Arquivos:
- `core/state_store.py`

## A2) Loop/scheduler por par
- `MainMonitor.run()` percorre `self.pairs` em cada ciclo.
- `self.pairs` combina pares do INI com pares do DB (`config_pairs`).

Arquivos:
- `core/monitors.py`

## A3) Execution com símbolo dinâmico
- `OrderRouter` recebe `pair` no fluxo de reprice e resolve símbolo local por exchange; criação de ordem usa `global_pair=pair`.
- Sem hardcode funcional de `SOL`/`SOLUSDT` para execução.

Arquivos:
- `core/order_router.py`
- `exchanges/exchanges_client.py`

## A4) Persistência por par
- `orders`, `fills` e `paper_orders` incluem campo `pair`.
- `paper_orders` guarda também `risk_percentage` por execução.

Arquivos:
- `core/state_store.py`

## A5) Dashboard/API para editar par
- **Antes da auditoria:** não havia rota explícita para CRUD de `config_pairs`.
- **Ajuste mínimo aplicado:**
  - `GET /api/bot-config` lista configs por par.
  - `POST /api/bot-config` cria/atualiza (`upsert`) config por par.

Arquivos:
- `api/handlers.py`
- `api/server.py`

Impacto: habilita operação do requisito do cliente sem editar DB manualmente.

---

## B1) Onde `%` é armazenada
- Persistida em SQLite (`config_pairs.risk_percentage`).

Arquivo:
- `core/state_store.py`

## B2) Reload em runtime
- Worker recarrega configs por par durante o loop com cache TTL (`BOT_CONFIG_CACHE_TTL_SEC`).
- Log de reload por par em cada ciclo.

Arquivo:
- `core/monitors.py`

## B3) Uso da `%` no sizing
- `risk_percentage` limita notional/qty no cálculo de posição.
- Valor é propagado no fluxo `monitor -> router.reprice_pair -> _calc_amount`.

Arquivo:
- `core/order_router.py`

## B4) Logging de validação
- **Ajuste mínimo aplicado:** novo log `[position_sizing]` com:
  - `pair`
  - `risk_percentage`
  - `balance_used_usdt`
  - `qty`
  - `notional_usdt`

Arquivo:
- `core/order_router.py`

---

## Como testar manualmente (passo a passo)

1. Iniciar API e worker.
2. Criar dois pares:
   - `POST /api/bot-config` para `SOL/USDT`
   - `POST /api/bot-config` para `BTC/USDT`
3. Confirmar lista:
   - `GET /api/bot-config`
4. Observar logs de execução por ambos os pares.
5. Alterar `risk_percentage` de um par (ex.: 1.0 -> 5.0) via `POST /api/bot-config`.
6. Aguardar próximo ciclo e validar logs `[config_reload]` e `[position_sizing]` com novo valor.

---

## Recomendações e próximos passos

1. **Frontend:** adicionar tela de gestão de `config_pairs` (CRUD por par) no dashboard.
2. **Validação operacional:** criar endpoint de health específico do worker (status do ciclo e timestamp do último reload).
3. **Governança de config:** padronizar fonte única de pares (preferencialmente DB) para reduzir divergência entre `config.txt` e `config_pairs`.
4. **Observabilidade:** evoluir logs para JSON estruturado e incluir `cycle_id` em todo fluxo live.
