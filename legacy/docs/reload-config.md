# Reload dinâmico de `bot_config`

## O que foi implementado

Foi implementado o modelo obrigatório de **refresh de configuração por ciclo** no worker (`MainMonitor`), com cache em memória por par e TTL curto.

### Fluxo

1. A cada ciclo do loop, o monitor chama `_refresh_pairs_from_db()` para sincronizar pares do banco (`config_pairs`) com os pares do arquivo (`PAIRS.LIST`).
2. Para cada par, o monitor chama `_load_pair_config(pair, now)`:
   - Usa cache em memória com TTL (`GLOBAL.BOT_CONFIG_CACHE_TTL_SEC`, default `5` segundos).
   - Quando cache expira, recarrega `pair/strategy/risk_percentage/max_daily_loss/enabled/updated_at` do banco.
3. O ciclo usa os valores atuais para:
   - habilitar/pausar execução (`enabled`)
   - validar estratégia ativa (`strategy`)
   - enviar parâmetros de risco ao router (`risk_percentage`, `max_daily_loss`)
4. Se `enabled=false`, o par é ignorado no próximo ciclo (com log explícito).

## Logs adicionados

Por par e por ciclo:

- `ts` (UTC)
- `pair`
- `updated_at` (ou `n/a`)
- `enabled`
- `risk_percentage`
- `strategy`

Prefixo do log: `[config_reload]`.

## Como testar localmente

1. Inicie o bot/API normalmente.
2. Atualize um registro na tabela `config_pairs` (via dashboard/API que grava no banco).
3. Verifique no log do worker o próximo ciclo:
   - `risk_percentage` novo sendo aplicado
   - `enabled=false` fazendo o par ser ignorado
4. Opcional: ajuste `GLOBAL.BOT_CONFIG_CACHE_TTL_SEC` para reduzir/aumentar frequência de leitura no banco.

## Redis Pub/Sub

Nesta etapa, **não foi implementado listener Pub/Sub** porque o projeto atual não possui integração Redis existente no fluxo de configuração. O reload por ciclo já atende o requisito obrigatório com mudanças mínimas.
