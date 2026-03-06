# Manual - Moedas, Pares e Simbolos por Exchange

Data: 2026-03-05

## Objetivo
Guiar o usuario para:
- cadastrar credenciais por exchange
- mapear simbolos BUY/SELL por exchange
- configurar percentual de compra/venda por par
- colocar o robo para rodar em PAPER/LIVE com menos passos

## Onde fazer no frontend
1. Aba `Fluxo Rapido`:
- Passo 1: credenciais
- Passo 2: par + simbolos por exchange (inclui salvamento em lote)
- Passo 3: estrategia (% compra, % venda, stake)
- Passo 4: rodar PAPER/LIVE
2. Aba `Exchanges`:
- cadastro/rotacao/teste de credenciais sem modal (formulario inline)
3. Aba `Moedas e Pares`:
- cadastro manual avancado de mapeamentos

## Fluxo recomendado (simples)
1. Cadastrar e testar credenciais no Passo 1.
2. Definir um `Par` global no Passo 2 (ex.: `VISTA/USDT`).
3. Preencher os simbolos locais por exchange no bloco `Salvar simbolos em lote por exchange`.
4. Salvar estrategia no Passo 3 (stake + risco%).
5. Rodar em `PAPER` e validar.
6. Depois mudar para `LIVE`.

## Validacao de credencial (atualizada em 2026-03-05)
- O bot agora valida 2 etapas no teste de credencial:
  - conectividade/autenticacao (`fetch_balance`/`fetch_time`)
  - endpoint privado de ordens (`fetch_open_orders`, com fallback para `fetch_orders`/`fetch_my_trades`)
- Com isso, reduz falso `OK` quando a chave conecta, mas falha na hora de operar.
- Em caso de erro, o frontend mostra motivo + hint (ex.: `AUTH_FAILED`, `PERMISSION_DENIED`, `TIMESTAMP_WINDOW`).

## Caso pratico: VISTA em 4 exchanges (2 BRL + 2 USD)
Use o mesmo par global para todas, por exemplo `VISTA/USDT`.

No Passo 2, em lote, configure assim:
- `novadax` -> BUY `VISTA/BRL`, SELL `VISTA/BRL`
- `mercadobitcoin` -> BUY `VISTA/BRL`, SELL `VISTA/BRL`
- `gateio` -> BUY `VISTA/USDT`, SELL `VISTA/USDT`
- `mexc` -> BUY `VISTA/USDT`, SELL `VISTA/USDT`

Observacao: o par global e a referencia unica da estrategia. O simbolo local muda por exchange conforme o mercado disponivel (BRL, USD, USDT).

## Moeda listada em apenas 1 exchange
Comportamento atual (2026-03-05):
- se a moeda/par nao estiver listado em uma exchange, o robo ignora essa exchange para aquele par
- se estiver listado somente na Gate.IO (ou somente na NovaDAX), o robo opera apenas onde houver listagem valida
- as outras exchanges seguem ativas para os demais pares que forem validos nelas

Exemplo:
- voce adiciona `MOEDA_X/USDT` no radar
- Gate.IO tem `MOEDA_X/USDT`
- NovaDAX nao tem esse mercado
- resultado: para `MOEDA_X/USDT`, Gate.IO entra no ciclo; NovaDAX e ignorada automaticamente

## Atalho no Passo 2
No bloco de lote, cada exchange tem botoes rapidos:
- `BRL`
- `USD`
- `USDT`

Eles preenchem BUY/SELL automaticamente com `<BASE>/<QUOTE>`.
Exemplo: para `VISTA/USDT`, clicar `BRL` vira `VISTA/BRL`.

## Como funciona internamente
Ao salvar mapeamento, o sistema sincroniza automaticamente:
- tabela `pair_mappings` (SQLite)
- `[SYMBOLS]` no config ativo (`exchange.par.buy/sell`)
- `[PAIRS] LIST`

Assim o worker passa a usar os simbolos novos sem edicao manual de arquivo.

## Automacao e flutuacao
No Passo 3:
- `% Compra` define alvo abaixo do preco vigente
- `% Venda` define alvo acima do preco vigente
- o robo remarca ordem com base no preco vigente conforme regras de repricing

## Regra de sizing (atualizada em 2026-03-05)
- Se `STAKE` do par estiver preenchido (`FIXO_USDT`), o robo usa esse valor.
- Se `STAKE` do par estiver `0`/ausente e `risk_percentage > 0`, o robo usa fallback automatico:
  - BUY: `saldo_quote * risk_percentage`
  - SELL: `saldo_base * risk_percentage`
- Depois do calculo, o roteador ainda ajusta para os minimos da exchange (min_qty/min_notional) e para saldo disponivel.
- Isso evita o bloqueio com `amount_calc=0.0` quando o usuario esquece de salvar stake no par.
- Limite de ordens ativas por par:
  - `max_open_orders_per_symbol = 0` significa sem limite.
  - o fallback de limite legacy nao e aplicado quando o campo ja existe no `bot_config`.

## Cancelamento manual pelo usuario
Configuracao atual:
- `recreate_after_external_cancel = false`

Com isso, quando o usuario cancelar uma ordem manualmente na exchange, o robo nao recria automaticamente esse lado.

## Troubleshooting rapido
1. Erro ao criar credencial:
- agora o frontend mostra detalhes de validacao (campo/erro) e `correlationId`.
- verifique `label`, `apiKey`, `apiSecret` e caracteres permitidos.

2. Nao aparece ordem na exchange:
- confirmar credencial `ACTIVE` e teste `OK`.
- se o teste falhar com `TIMESTAMP_WINDOW`, sincronizar data/hora do Windows e testar de novo.
- se o teste falhar com `PERMISSION_DENIED`, recriar API key com permissao de trade e leitura de ordens.
- confirmar mapeamento no Passo 2 para cada exchange.
- confirmar modo `LIVE` (em `PAPER` nao envia ordem real).
- para `VISTA`, usar `.../BRL` em NovaDAX/MercadoBitcoin e `.../USDT` em Gate/MEXC.
- abrir o Passo 3 e salvar `Stake USDT` para o par; se nao salvar stake, deixar `Risco %` maior que zero para o fallback automatico entrar.
- se aparecer `MARKETDATA_STALE_BLOCK` no log, o robo agora tenta fallback de livro por polling; se persistir, validar conectividade/API da exchange.
- reiniciar pelo `EXECUTAR_TRADINGBOT.bat` (agora ele derruba instancias antigas automaticamente antes de subir).

3. Simbolo invalido:
- revisar se a exchange usa `.../BRL`, `.../USD` ou `.../USDT` para aquele ativo.

## Endpoints relacionados
- `GET /api/tenants/{tenantId}/exchange-credentials`
- `POST /api/tenants/{tenantId}/exchange-credentials`
- `POST /api/tenants/{tenantId}/exchange-credentials/{id}/test`
- `GET /api/tenants/{tenantId}/assets-pairs`
- `POST /api/tenants/{tenantId}/assets-pairs/pairs`
- `DELETE /api/tenants/{tenantId}/assets-pairs/pairs?pair=...&exchange=...`
