# Testes de Paper Trading Multi-par

## Como rodar

```bash
python -m unittest tests.test_paper_multipair -v
```

## Dependências locais

Os testes usam apenas SQLite local (arquivo temporário). Não precisam Redis.

Se quiser validar com DB real do projeto:

1. Ajuste `GLOBAL.SQLITE_PATH` para um arquivo de teste.
2. Garanta que a tabela `config_pairs` tenha os campos `symbol`, `enabled`, `strategy`, `risk_percentage`, `max_daily_loss`.

## Cenários cobertos

- `paper_two_pairs_should_run_in_parallel_or_interleaved`: executa `SOL/USDT` e `BTC/USDT` no mesmo run em modo paper.
- `risk_percentage_update_should_reflect_next_cycle`: atualiza `risk_percentage` no DB durante execução e valida o valor no ciclo seguinte.
- `position_size_should_change_with_risk_percentage`: valida numericamente que maior `%` gera maior quantidade.

## Reproduzir update de % em runtime

Durante um loop ativo, rode um update SQL no `config_pairs` para o par desejado:

```sql
UPDATE config_pairs
SET risk_percentage = 5.0,
    updated_at = strftime('%s','now')
WHERE symbol = 'SOLUSDT';
```

No ciclo seguinte, os eventos `paper_exec` e os registros em `paper_orders` passam a refletir o novo valor.
