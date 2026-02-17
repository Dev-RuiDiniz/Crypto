# 04 - Strategies

## Spread
- Calcula preços alvo por percentual configurado por par.
- Reavalia mercado e executa cancelamento/reinserção quando necessário.
- Suporta múltiplos pares em paralelo.

## Arbitragem simples
- Detecta oportunidade básica entre exchanges configuradas.
- Executa em modo paper/live conforme `GLOBAL.MODE`.
- Usa controles de risco e idempotência por perna para reduzir duplicidade.
