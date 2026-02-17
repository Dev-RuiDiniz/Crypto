# 02 - Setup

## Requisitos
- Python 3.11+
- Node.js 18+ (frontend)

## Instalação backend
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Variáveis de ambiente
- `EXCHANGE_CREDENTIALS_MASTER_KEY` (obrigatória para cofre de credenciais)
- `TRADINGBOT_TENANT_ID` (opcional)
- SMTP/Webhook apenas via configuração de notificações + env de runtime.

## Banco de dados
- SQLite local (`GLOBAL.SQLITE_PATH`, padrão `./data/state.db`).
- Estrutura criada automaticamente por `StateStore` na inicialização.

## Frontend
```bash
cd frontend
npm ci
npm run build
```
