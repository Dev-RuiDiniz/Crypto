# 12 - Paper vs Live

## Modo PAPER
- Não envia ordens reais para exchange.
- Simula create/cancel e registra em `paper_orders`.

## Modo LIVE
- Usa clientes reais CCXT/MB v4.
- Requer credenciais válidas no vault e controles de risco ajustados.

## Alternância
- Configuração em `[GLOBAL] MODE = PAPER|REAL`.

## Recomendação
- Validar multipar em PAPER antes de habilitar LIVE.
