# 09 - Go Live

Checklist mínimo antes de produção controlada:
1. Validar modo PAPER com os pares finais.
2. Confirmar limites de risco por par e global.
3. Validar notificações (email/webhook).
4. Revisar status de circuit breaker e health endpoints.
5. Confirmar credenciais trade-only (sem withdraw).
6. Executar janela piloto com tamanho reduzido.


## Configuração operacional via Frontend (runtime)
- Todas as configurações operacionais (credenciais, pares, spread, arbitragem, risco, notificações) devem ser realizadas via UI com persistência em SQLite.
- Alterações de ADMIN geram auditoria (`audit_logs`) e são refletidas no worker sem restart (próximo ciclo).
- VIEWER permanece read-only em todas as telas de configuração.
