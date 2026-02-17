# 01 - Setup

## Requisitos
- Python 3.11+
- Node.js (para frontend, se necessário rebuild)

## Instalação
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Variáveis de ambiente
- `EXCHANGE_CREDENTIALS_MASTER_KEY` (obrigatória para cofre de credenciais)
- `TRADINGBOT_TENANT_ID` (opcional, default `default`)

Use `.env.example` como referência.

## Arquivo de config
- Base: `config.txt`
- Template: `config.template.txt`

## Execução
- Worker/API via launcher legado:
```bash
python run_arbit.py
```
- Worker direto:
```bash
python bot.py --config config.txt
```
- API direta:
```bash
python -m api.server --config config.txt
```
