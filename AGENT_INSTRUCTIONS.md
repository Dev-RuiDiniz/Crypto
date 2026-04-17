# AI Agent Instructions - Crypto Trading Bot Context

This repository contains a Cryptocurrency Trading Platform with multi-pair execution, real-time risk management, and both Paper and Live modes.
As an AI Agent or Skill interacting with this repository, you MUST adhere to the constraints and rules defined here.

## 1. System Architecture
- **Backend Stack:** Python 3.11+, Flask (API).
- **Frontend Stack:** Node.js 18+, frontend directory.
- **Database:** Local SQLite (`data/state.db` typically). StateStore handles schema evolution.
- **Workflow:** 
  `Frontend` -> `API Flask` -> `Worker Assíncrono` -> `Estratégias (Spread/Arbitragem)` -> `RiskPolicy & Circuit Breaker` -> `ExchangeHub & MarketData` -> `SQLite`

## 2. Modes of Operation
- **Paper Trading:** Default mode for testing. Does NOT send real orders to the exchange. Simulates fills based on WS/Poll orderbook data.
- **Live Trading:** Real API calls. **WARNING**: Any change regarding order placement must be tested heavily in Paper mode first.

## 3. Strict Security & Risk Rules
- **Credentials:** Handled via API/dashboard encrypted in rest. No hardcoded keys. Keys must be `trade-only`.
- **Risk Policy:** Any modification to order sizing, frequency, or pricing must pass through the consolidated `RiskPolicy` module.
- **Idempotency:** All orders dispatched must have a deterministic `clientOrderId` to prevent duplicate orders during network failures.

## 4. Development Workflow & Decision Logging (ADRs)
- Changes with architectural impact, new exchange integrations, or database changes **MUST** be documented as an Architecture Decision Record (ADR) in `docs/adr/`.
- If a user asks you to build a new feature or change flow logic, propose a plan first or write an ADR before modifying core modules.
- Ensure all alerts (email/webhook) and kill switches (Circuit breaker) are maintained.

## 5. Execution Commands
- **Windows (Single Click Client):** `EXECUTAR_TRADINGBOT.bat`
- **Backend/Worker:** `python run_arbit.py`
- **Frontend Build:** `cd frontend && npm ci && npm run build`

## 6. Your Role
Your primary duty is to ensure the **RiskPolicy** and **Circuit Breaker** are respected, never compromise security protocols, and maintain proper documentation of design choices via ADRs.
