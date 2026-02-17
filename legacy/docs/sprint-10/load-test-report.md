# Sprint 10 — Load Test Leve (Multi-par)

## Cenário
- Script: `tests/load_test_multi_pair.py`
- Pares simulados: BTC-USDT, ETH-USDT, SOL-USDT, XRP-USDT, ADA-USDT
- Estratégias/fluxos exercitados por leitura operacional: mids, ordens abertas, market data status, métricas.

## Resultado
- Execução depende de API/worker em execução local.
- Em ambiente CI sem serviços ativos, o script valida estrutura e pode retornar erro de conexão.

## Métricas-alvo
- Estabilidade: sem crash do processo durante a janela de execução.
- Crescimento de memória: controlado (sem crescimento linear contínuo).
- Latência média: manter baixa para endpoints de leitura operacional.

## Comando sugerido
```bash
python tests/load_test_multi_pair.py --base-url http://127.0.0.1:8000 --minutes 3 --concurrency 4
```
