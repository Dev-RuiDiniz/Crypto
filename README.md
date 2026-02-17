# Robô de Trading Cripto — Entrega Final

## 4.1 O que é o sistema
Plataforma de trading automático para cripto, com execução multipar, integração com exchanges, gestão de risco centralizada e interface web para operação em modo paper e live.

## 4.2 O que ele faz
- Order book em tempo real com WS quando disponível e fallback para polling.
- Estratégia de spread com ajuste automático por percentual.
- Cancelamento/reinserção de ordens quando alvo muda.
- Arbitragem simples entre exchanges (com suporte operacional em paper/live).
- Configuração via dashboard/API: pares, percentuais, limites de risco e status.
- Gestão de risco consolidada (`RiskPolicy`) e bloqueios auditáveis.
- Alertas por e-mail e webhook (WhatsApp via integração de webhook).
- Circuit breaker por exchange.
- Idempotência de ordens com `clientOrderId` determinístico.

## 4.3 Arquitetura resumida
```text
Frontend -> API Flask -> Worker assíncrono
                       -> Estratégias (Spread/Arbitragem)
                       -> RiskPolicy + Circuit Breaker
                       -> ExchangeHub + MarketData(WS/Poll fallback)
                       -> SQLite + logs + notificações
```

## 4.4 Como instalar
### Requisitos
- Python 3.11+
- Node.js 18+

### Dependências
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Variáveis de ambiente
- `EXCHANGE_CREDENTIALS_MASTER_KEY` (obrigatória)
- `TRADINGBOT_TENANT_ID` (opcional)

### Banco de dados
- SQLite local definido por `GLOBAL.SQLITE_PATH` (padrão `./data/state.db`).

### Migrations
- O `StateStore` aplica criação/evolução de schema na inicialização.

## 4.5 Como rodar
### Backend + Worker (launcher)
```bash
python run_arbit.py
```

### Worker isolado
```bash
python bot.py --config config.txt
```

### Frontend
```bash
cd frontend
npm ci
npm run build
```

## 4.6 Como configurar
- **Credenciais**: via API/dashboard de credenciais (criptografadas em repouso).
- **Pares**: seção `[PAIRS]` e painel de configuração.
- **Spread %**: seção `[SPREAD]` por par.
- **Arbitragem**: habilitação por par/configuração runtime.
- **Risco**: limites globais e por par em `RiskPolicy`.
- **Alertas**: canais e severidade por tenant.

## 4.7 Como usar
1. Adicionar credenciais de exchange.
2. Configurar pares e spread.
3. Definir limites de risco.
4. Ativar estratégia (paper primeiro).
5. Monitorar status e health endpoints.
6. Interpretar logs e eventos de risco/notificação.

## 4.8 Paper vs Live
- **PAPER**: simulação, sem envio real de ordens.
- **LIVE**: ordens reais nas exchanges habilitadas.
- Recomendado: validar integralmente em paper antes de live.

## 4.9 Segurança
- Usar somente chaves **trade-only**.
- Nunca habilitar permissão de **withdraw**.
- Manter limites de risco conservadores no início.
- Não expor segredos em frontend/logs.

## 4.10 Checklist de Go-Live
- [ ] Multipar validado em paper.
- [ ] RiskPolicy e kill switch revisados.
- [ ] Alertas (email/webhook) testados.
- [ ] Circuit breaker monitorado.
- [ ] Health endpoints e dashboard estáveis.
- [ ] Janela piloto com tamanho reduzido executada.

---

## Índice da documentação consolidada
- `docs/00-overview.md`
- `docs/01-architecture.md`
- `docs/02-setup.md`
- `docs/03-configuration.md`
- `docs/04-strategies.md`
- `docs/05-risk.md`
- `docs/06-marketdata.md`
- `docs/07-notifications.md`
- `docs/08-circuit-breaker.md`
- `docs/09-go-live.md`
- `docs/10-troubleshooting.md`
- `docs/11-paper-vs-live.md`
- `docs/production-runbook.md`
