# Auditoria — Bot de Trading Spot (Proposta Técnica)

## 1. Resumo executivo

**Status geral:** o repositório está **funcional como bot de arbitragem/market making básico em modo PAPER/REAL com painel web simples**, porém **ainda distante do MVP completo descrito na proposta técnica de Bot Spot com execução e monitoramento**.

- Há núcleo operacional mínimo (conexão com exchanges via CCXT, criação/cancelamento de ordens, monitor principal, snapshot para painel).
- Há painel administrativo básico (visualização de saldos, ordens, mids e edição de config no `config.txt`).
- Há persistência local em SQLite/CSV para ordens/fills/eventos.
- Faltam pilares críticos da proposta: autenticação/autorização, RBAC, fila/scheduler, banco relacional robusto (Postgres), observabilidade com métricas/tracing, notificações (Telegram/WhatsApp), runbook formal, pipeline CI/CD e testes de qualidade mínimos.

**Riscos principais (técnicos/segurança/operação):**

1. **Segurança crítica:** chaves e credenciais aparentam estar em texto puro no `config.txt` versionado.
2. **API sem autenticação:** endpoints administrativos sem JWT/RBAC.
3. **Operação frágil:** sem orquestração por serviços separados (API/worker/queue), sem retry centralizado de jobs, sem circuit breakers completos.
4. **Observabilidade incompleta:** logs textuais (não JSON estruturado), sem métricas e sem tracing.
5. **Qualidade insuficiente para produção:** cobertura de testes praticamente inexistente.

**Para rodar em produção com segurança falta, no mínimo:**
- remover segredos do repositório + secret manager;
- autenticação JWT + RBAC;
- isolamento de processos (API + worker + fila + banco);
- observabilidade real (métricas + alertas + dashboards + tracing opcional);
- testes unitários/integração e pipeline CI;
- runbook operacional e plano de incidentes.

---

## 2. Inventário do repositório

### 2.1 Estrutura de pastas (resumo)

| Caminho | Tipo | Papel observado |
|---|---|---|
| `bot.py` | Backend Python | Entrypoint principal do bot (loop assíncrono, bootstrap, cancelamento inicial de ordens). |
| `core/` | Backend Python | Núcleo de estratégia, roteamento, risco, monitor, portfólio e persistência local. |
| `exchanges/` | Backend Python | Hub de exchanges (CCXT) e adapter específico Mercado Bitcoin v4. |
| `api/` | Backend Python (Flask) | API HTTP e servidor de assets do frontend. |
| `frontend/src/` | Frontend (React sem build tool) | Dashboard e tela de configurações consumindo `/api/*`. |
| `frontend/electron/` | Desktop packaging | Empacotamento Electron para app desktop. |
| `data/` | Dados locais | SQLite (`state.db`), snapshot e CSVs. |
| `logs/` | Operação local | Logs do bot. |
| `requirements.txt` | Dependências Python | CCXT, aiohttp, tenacity, etc. |
| `config.txt` | Configuração runtime | Parâmetros globais, risco, exchanges e símbolos (inclui segredos). |

### 2.2 Serviços/processos identificados

- **Processo do bot** (`python bot.py config.txt`):
  - conecta exchanges;
  - executa estratégia/roteador/monitor em loop;
  - publica snapshot para API/UI.
- **Processo da API Flask** (`python -m api.server` ou equivalente):
  - expõe endpoints de leitura e atualização de configuração;
  - serve frontend estático.
- **Processo opcional Electron** (`npm run start` em `frontend/electron`):
  - encapsula UI+API para desktop.

### 2.3 Dependências relevantes

- Python: `ccxt`, `aiohttp`, `tenacity`, `pytz`, `colorama`.
- Frontend: React via CDN (`esm.sh`), sem bundler robusto.
- Desktop: Electron + electron-builder.

---

## 3. Matriz “Proposta Técnica x Repositório”

## Entrega A — Núcleo do Bot (Core)

| Bloco | Status | Evidências | Lacunas e riscos | Próximas ações |
|---|---|---|---|---|
| Market Data Ingestion (REST/WS, OHLC, book, trades; normalização) | 🟨 PARCIAL | `ExchangeHub` usa CCXT async para conexão e cotações/livro aberto; normalização de quote/local-USDT e símbolos via `[SYMBOLS]`; snapshot de mids e ordens no monitor. | Não há pipeline explícito de ingestão OHLC/trades persistidos; WS não está claramente implementado como stream contínuo dedicado; sem barramento de dados. | - Formalizar camada de ingestão (REST+WS).<br>- Persistir OHLC/trades.<br>- Contratos de normalização documentados. |
| Strategy Engine (configurável por par: horários, gatilhos, filtros) | 🟨 PARCIAL | `core/strategy_spread.py` lê spreads por par e gera planos BUY/SELL com cooldowns e parâmetros por par/lado. | Não há gestão clara de janelas de horário trading, filtros avançados, múltiplas estratégias plugáveis. | - Criar interface de estratégia plugável.<br>- Adicionar scheduler de horários por par.<br>- Implementar filtros de regime/volatilidade. |
| Risk Manager (limites, SL/TP, trailing, max posições, kill switch, drawdown) | 🟨 PARCIAL | `core/risk_manager.py` implementa limites de ordens abertas, teto de exposição e kill-switch de drawdown (parcial/placeholder). | SL/TP/trailing não implementados como mecanismos formais; controle de max posições incompleto; drawdown depende de cálculo de equity ainda limitado. | - Implementar engine de risco por posição (SL/TP/trailing).<br>- Definir cálculo consistente de equity e drawdown.<br>- Cobrir testes de risco. |
| Execution Engine (create/cancel, reconciliação status, idempotência, tolerância falhas, fallback opcional) | 🟨 PARCIAL | `core/order_router.py` + `core/order_manager.py` + `exchanges/exchanges_client.py`: criação/cancelamento, retries (`tenacity`), boot cancel all, polling de fills/open orders, modo paper. | Idempotência formal por chave externa e reconciliação completa pós-falha não estão estruturadas com garantia transacional; sem fila para reprocessamento robusto. | - Implementar idempotency keys persistentes.<br>- Reconciliação periódica robusta (ordens/fills) com reprocessamento.<br>- Inserir fila de comandos com retries e DLQ. |
| Portfolio & PnL (saldo, posições, preço médio, PnL realizado/não-realizado) | 🟨 PARCIAL | `core/portfolio.py` calcula stake e snapshot de saldos; `state_store.py` guarda fills/orders; painel mostra saldos/ordens. | Não há módulo claro de posições com preço médio e PnL realizado/não-realizado consolidado por par/exchange. | - Criar tabela/modelo de posições.<br>- Calcular PnL realizado e não-realizado.<br>- Expor endpoints e visualização de PnL. |

## Entrega B — Dashboard Web (Admin)

| Bloco | Status | Evidências | Lacunas e riscos | Próximas ações |
|---|---|---|---|---|
| Status do bot (ON/OFF) | 🟨 PARCIAL | Dashboard atual mostra dados e última atualização; API possui `/api/ping` e `/api/debug`. | Não existe controle operacional explícito ON/OFF do worker via API autenticada. | - Endpoint/control plane para start/stop seguro do bot.<br>- Exibir estado real do worker (health + liveness). |
| Config por par (estratégia, risco, limites) | ✅ PRONTO (básico) | `frontend/src/components/Config.js` + `/api/config` GET/POST (`api/handlers.py`) editam parâmetros de config por JSON/INI. | Sem validação robusta por schema/versionamento e sem trilha de auditoria completa de mudanças. | - Adotar schema (Pydantic/JSONSchema).<br>- Versionar configurações e manter histórico auditável. |
| Visualização execuções, ordens, PnL, erros/alertas | 🟨 PARCIAL | UI mostra saldos/mids/ordens e eventos (`Dashboard.js`, `/api/orders`, `/api/balances`, `/api/events`). | Falta visão de execuções detalhada e PnL completo; alertas críticos não estruturados. | - Painel de fills/executions completo.<br>- Painel PnL diário/acumulado.<br>- Centro de alertas com severidade. |
| Ações: pausar/retomar, cancelar todas, fechar posições | 🟨 PARCIAL | Existe lógica de cancel all no boot e métodos internos de cancelamento. | Ações administrativas não expostas como fluxo completo no dashboard/API. Fechar posição não está implementado como ação dedicada. | - Endpoints administrativos autenticados.<br>- Botões de pausa/retomada/cancelar tudo/flatten com confirmação. |

## Entrega C — Notificações e Alertas

| Bloco | Status | Evidências | Lacunas e riscos | Próximas ações |
|---|---|---|---|---|
| Telegram/WhatsApp para execuções e erros críticos | ❌ FALTA | Não foram encontradas integrações com Telegram/WhatsApp/provedores no backend. | Sem notificação out-of-band para incidentes críticos. | - Implementar notifier provider (Telegram primeiro).<br>- Templates de mensagem e regras por severidade. |
| Alertas de rate limit, drawdown, ordens presas | 🟨 PARCIAL | Há logs/warnings em cancelamentos/retries e eventos de monitor; risco contém parâmetro de drawdown. | Sem sistema de alertas ativo com canais e regras formais. | - Motor de alertas com thresholds.<br>- Persistência + deduplicação + envio externo. |

## Entrega D — Auditoria, Logs e Observabilidade

| Bloco | Status | Evidências | Lacunas e riscos | Próximas ações |
|---|---|---|---|---|
| Logging estruturado (JSON + correlationId) | ❌ FALTA | `utils/logger.py` usa formatters textuais para console/arquivo. | Não há JSON logging nem correlationId transacional/ciclo formal. | - Migrar para logging JSON.<br>- Incluir correlationId por ciclo/ordem.<br>- Padronizar campos obrigatórios. |
| Métricas (ordens/min, sucesso, latência, PnL, falhas) | ❌ FALTA | Não há exportador Prometheus/StatsD. | Operação sem SLO/SLI mensurável. | - Expor `/metrics` e coletar counters/histograms.<br>- Dashboard de métricas operacionais. |
| Tracing (OpenTelemetry) | ❌ FALTA | Não há dependências/configuração OTel. | Diagnóstico distribuído inexistente. | - Instrumentar API/worker com OTel (opcional no MVP+). |
| Runbook (operar/pausar/recuperar) | 🟨 PARCIAL | `README_run.txt` contém instruções operacionais básicas locais. | Não há runbook formal de incidentes, rollback, recovery e SOPs de produção. | - Criar `docs/RUNBOOK.md` com cenários de incidente.
|

## Sistemas / Arquitetura necessários

| Item | Status | Evidências | Lacunas e riscos | Próximas ações |
|---|---|---|---|---|
| API/Dashboard com Auth JWT + RBAC | ❌ FALTA | API Flask sem camada de auth; endpoints públicos. | Risco alto de controle não autorizado. | - Implementar autenticação JWT + RBAC Admin/Viewer. |
| Worker do bot separado | 🟨 PARCIAL | Bot roda em processo próprio (`bot.py`) separado da API por execução manual. | Sem supervisão/orquestração formal e sem contrato entre serviços. | - Docker Compose com serviços separados e healthchecks. |
| Fila/Scheduler (Redis+Celery/RQ) | ❌ FALTA | Não há Redis/Celery/RQ no código/deps. | Sem processamento assíncrono resiliente. | - Introduzir Redis + fila para comandos/eventos. |
| Banco (Postgres preferencial) | 🟨 PARCIAL | Há SQLite local (`core/state_store.py`) com `orders/fills/event_log`. | Sem Postgres/migrations, sem tabelas ricas para configs/auditoria/posições completas. | - Migrar para Postgres + Alembic.<br>- Modelagem completa de domínio. |
| Cache/State (Redis locks/rate limit) | ❌ FALTA | Sem Redis e sem locks distribuídos. | Estado rápido e coordenação frágeis. | - Introduzir Redis para locks/estado efêmero/rate-limit. |
| Observabilidade (Prom/Grafana/OTel) | ❌ FALTA | Não identificado stack de observabilidade. | Baixa confiabilidade operacional. | - Adotar stack mínima de métricas + dashboards + alertas. |
| Adapter unificado por exchange | ✅ PRONTO (básico) | `ExchangeHub` abstrai exchanges com CCXT + `MBV4Adapter` para privadas MB. | Necessita ampliar contrato para cenários de erro/reconciliação avançada. | - Formalizar interface e testes de contrato por adapter. |

## Segurança

| Item | Status | Evidências | Lacunas e riscos | Próximas ações |
|---|---|---|---|---|
| Chaves nunca no front | 🟨 PARCIAL | Frontend não contém chave explícita; configuração ocorre no backend via arquivo. | `config.txt` com segredos em texto puro no repo/host. | - Remover segredos versionados imediatamente.<br>- Usar `.env`/secret manager e templates. |
| Secrets via env/.env e orientação produção | ❌ FALTA | Não há padrão consolidado `.env.example` e guia de secrets para produção. | Exposição acidental de credenciais. | - Criar `.env.example` + docs de segurança. |
| Permissões API sem withdraw | 🟨 PARCIAL | Não há enforcement no sistema; depende de configuração manual nas exchanges. | Sem validação automática de escopo das keys. | - Checklist e validação de permissões na inicialização. |
| Trilha de auditoria para mudanças de config | 🟨 PARCIAL | Existe `event_log` em SQLite e update de config via API. | Mudanças de config não têm trilha completa (quem/quando/antes/depois) com autenticação. | - Registrar diff de config com usuário autenticado. |

## Qualidade e Testes

| Item | Status | Evidências | Lacunas e riscos | Próximas ações |
|---|---|---|---|---|
| Unit tests (risco/sinal/idempotência) | ❌ FALTA | Não há suíte de testes unitários estruturada; apenas script `test_server.py` simples de endpoint. | Regressões prováveis. | - Adotar pytest e cobrir módulos críticos. |
| Integração sandbox/paper | 🟨 PARCIAL | Modo `PAPER` existe no core/exchange hub. | Não há suíte automatizada de integração nem fixtures sandbox formais. | - Criar testes integração com mocks/sandbox exchange. |
| Modo paper com book/ticker real | ✅ PRONTO (básico) | Fluxo paper usa dados de mercado e simula ordens no hub. | Precisa validação automatizada e relatórios. | - Adicionar cenários reprodutíveis e assertions. |

## Entregáveis finais (checagem)

| Entregável | Status | Observação |
|---|---|---|
| Bot funcionando Paper + Live | 🟨 PARCIAL | Paper e modo real existem; falta hardening e governança para produção segura. |
| Dashboard admin | 🟨 PARCIAL | Dashboard básico existe, mas sem auth e ações operacionais completas. |
| Conector(es) exchange alvo | ✅ PRONTO (básico) | Conectores via CCXT e adapter MB v4 presentes. |
| Banco com auditoria | 🟨 PARCIAL | SQLite com event_log, sem modelagem/auditoria corporativa. |
| Notificações | ❌ FALTA | Não implementado. |
| Observabilidade | ❌ FALTA | Sem métricas/tracing/alerting estruturado. |
| Documentação (setup/operação/runbook) | 🟨 PARCIAL | Existe README_run.txt; falta documentação consolidada robusta. |
| Docker + CI/CD | ❌ FALTA | Não encontrados Dockerfiles/compose/workflows. |

---

## 4. Arquitetura atual (como está hoje)

### 4.1 Diagrama textual (estado atual)

```text
+-----------------------+           +----------------------+
|   Bot Worker (bot.py) |           |  API Flask (api/*)   |
|-----------------------|           |----------------------|
| MainMonitor loop      |<--------->| /api/* handlers      |
| StrategySpread        | snapshot  | (lê memória/arquivo) |
| RiskManager           | shared    | serve frontend/src   |
| OrderRouter/Manager   | state     +----------+-----------+
| ExchangeHub (CCXT/MB) |                      |
+-----------+-----------+                      |
            |                                  v
            |                           +-------------+
            |                           | Frontend UI |
            |                           | React CDN   |
            |                           +-------------+
            |
            v
     +--------------+
     | Exchanges API|
     +--------------+

Persistência local:
- SQLite: data/state.db (orders, fills, event_log)
- CSV: data/orders.csv, data/fills.csv
- Snapshot JSON: data/api_snapshot.json
- Logs: logs/*.txt, logs/*.log
```

### 4.2 Fluxos principais

1. **Ciclo do bot (loop):**
   - coleta mercado (mids/open orders) e saldos;
   - estratégia gera planos por par;
   - risco valida limites;
   - router cria/move/cancela ordens;
   - monitor atualiza snapshot e eventos para API/UI.

2. **Execução de ordem:**
   - `OrderPlan` gerado;
   - `ExchangeHub` aplica criação (paper/real);
   - `StateStore` registra ordem/fill/evento;
   - UI consome via endpoints.

3. **Reconciliação pós-falha (atual):**
   - cancelamento opcional no boot;
   - polling de ordens abertas/fills;
   - sem engine robusta de replay/compensação com fila.

---

## 5. Segurança e compliance

### 5.1 Onde ficam secrets hoje

- Chaves e credenciais estão no `config.txt` (incluindo campos de API por exchange).
- Não há padrão obrigatório de `.env.example` + segredo externo.

### 5.2 Validações de permissão

- Não foi identificada validação automatizada de permissões de key (ex.: “trade only, sem withdraw”).
- Sem autenticação na API para proteger operações de configuração.

### 5.3 Recomendações (prioridade alta)

- **P0:** rotacionar imediatamente todas as chaves e remover do histórico de git.
- **P0:** introduzir `config.template.ini` sem segredos e carregar segredos por ambiente.
- **P0:** implementar JWT + RBAC e proteger endpoints administrativos.
- **P1:** auditar e registrar toda mudança de configuração com usuário/autenticação.

---

## 6. Observabilidade e operação

- **Logs estruturados JSON:** não; logs textuais.
- **CorrelationId:** não identificado por ciclo/ordem como campo padrão.
- **Métricas:** não identificado exportador/prometheus.
- **Dashboards observabilidade:** não identificado.
- **Runbook:** parcialmente em `README_run.txt`, sem padrão operacional de produção.

Recomendação mínima:
1. logging JSON + `cycle_id/order_id` obrigatório;
2. endpoint `/metrics` com métricas operacionais;
3. painéis e alertas de saúde/latência/falhas;
4. runbook com playbooks (pausa, retomada, incidentes de exchange, rate limit, reconciliação).

---

## 7. Testes e qualidade

### 7.1 O que existe

- Script manual `test_server.py` para consultar alguns endpoints.
- Scripts npm do frontend sem testes reais (`"test": "echo \"no tests yet\"`).

### 7.2 Como rodar (estado atual)

- Bot: `python bot.py config.txt`
- API: `python -m api.server`
- Front (servido pela API): abrir `http://127.0.0.1:8000`
- Script de endpoint: `python test_server.py`

### 7.3 O que falta (mínimo para MVP)

- Testes unitários para estratégia, risco, roteamento e idempotência.
- Testes de integração (paper/sandbox) com cenários reprodutíveis.
- Lint/quality gates automáticos no CI.

---

## 8. Plano até completar o MVP da proposta (checklist)

## P0 (bloqueadores de produção)

- [ ] Remover segredos do repositório e rotacionar chaves.
- [ ] Implementar auth JWT + RBAC (Admin/Viewer) na API.
- [ ] Criar docker-compose com serviços separados (api, worker, db, redis).
- [ ] Migrar persistência para Postgres com migrações.
- [ ] Implementar notificações Telegram para erros críticos/executions.
- [ ] Criar suíte mínima de testes unitários (risk/strategy/execution).

**DoD P0:** sistema sobe via compose, sem segredos versionados, endpoints críticos protegidos, testes mínimos passando.

## P1 (confiabilidade operacional)

- [ ] Introduzir fila/scheduler (Redis + Celery/RQ) para comandos e reconciliação.
- [ ] Implementar métricas (`/metrics`) e dashboard básico.
- [ ] Logging JSON com correlationId.
- [ ] Runbook de operação/incidentes.
- [ ] Painel com ações de pausa/retomada/cancel all/flatten.

**DoD P1:** operação monitorável com alertas e comandos administrativos auditáveis.

## P2 (evolução funcional)

- [ ] Módulo robusto de posições + PnL realizado/não realizado.
- [ ] Estratégias plugáveis por par, horários e filtros avançados.
- [ ] Tracing opcional com OpenTelemetry.

**DoD P2:** recursos avançados alinhados à proposta técnica completa.

### Dependências entre tarefas

- Segurança (P0) antecede exposição pública/produção.
- Banco + fila antecedem reconciliação robusta e trilhas auditáveis completas.
- Métricas/logging estruturado antecedem SRE e alertas maduros.

