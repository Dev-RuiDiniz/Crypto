# 03 - Configuration

## Fontes de configuração
1. `config.txt` (INI)
2. SQLite (`config_pairs`, `bot_global_config`, `config_version`)

## Campos importantes
- `[PAIRS] LIST`
- `[SPREAD] <PAIR>, <PAIR>_BUY_PCT, <PAIR>_SELL_PCT`
- `[RISK] MAX_OPEN_ORDERS_PER_PAIR_PER_EXCHANGE, MAX_GROSS_EXPOSURE_USDT`
- `[GLOBAL] MODE, LOOP_INTERVAL_MS, HTTP_TIMEOUT_SEC, MAX_RETRIES`

## Reload dinâmico
Alterações via API em `bot-config`/`bot-global-config` incrementam `config_version` e o monitor recarrega sem restart.
