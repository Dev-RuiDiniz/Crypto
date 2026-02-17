# 08 - Troubleshooting

## Problemas comuns
- **API no ar, worker stale/down**: validar `/api/health/worker` e logs do worker.
- **Config não aplica**: verificar `config_version` e `/api/config-status`.
- **Falha de credenciais**: conferir tenant, status ACTIVE e chave mestra.
- **Sem dados de mercado**: validar conectividade/rate-limit e exchanges habilitadas.

## Diagnóstico rápido
```bash
pytest -q tests/test_health_runtime.py tests/test_exchange_credentials_api.py
```
