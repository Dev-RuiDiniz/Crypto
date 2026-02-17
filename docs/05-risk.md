# 05 - Risk

A política central `RiskPolicy` valida cada intenção de ordem antes do envio.

## Regras
- Kill switch global e por par.
- Limite percentual por trade.
- Limite absoluto por trade.
- Máximo de ordens abertas.
- Máximo de exposição.

## Evidências operacionais
- Bloqueios persistidos em `risk_events`.
- API/Frontend exibem motivo de bloqueio e estado operacional.
