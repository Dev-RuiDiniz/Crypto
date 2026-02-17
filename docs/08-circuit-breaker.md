# 08 - Circuit Breaker

O circuito por exchange protege o sistema contra falhas repetidas de execução.

## Comportamento
- Conta falhas de envio/execução por exchange.
- Abre o circuito ao ultrapassar limite configurado.
- Durante circuito aberto, novas ordens são bloqueadas.
- Após timeout, entra em tentativa de recuperação controlada.
