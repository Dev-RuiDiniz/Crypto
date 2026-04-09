# Hardening MEXC 2026-04-09

## Resumo
- Escopo: reduzir divergencias da integracao MEXC Spot em timestamp, credenciais privadas e WebSocket de orderbook.
- Base de referencia: resposta oficial do suporte MEXC recebida em 2026-04-09.
- Entrega planejada em 4 commits: tempo/telemetria, credenciais/auth, websocket, documentacao.

## Resposta do suporte considerada
- `recvWindow` maximo suportado: `60000`.
- Endpoint recomendado para horario do servidor: `GET /api/v3/time`.
- Spot e Futures usam consultas e assinatura separadas.
- Recomendacao de heartbeat para WebSocket: enviar ping a cada 20 segundos.

## Diagnostico consolidado
### 1. Timestamp / recvWindow
- O sistema ja usava `recvWindow=60000` e `load_time_difference()`, mas a politica estava duplicada e pouco observavel.
- Faltava registrar contexto suficiente para responder ao suporte quando a falha ocorre e com qual offset.

### 2. Credenciais privadas
- O classificador antigo podia colapsar erros diferentes em `AUTH_FAILED`.
- Em MEXC isso e perigoso porque permissao insuficiente, restricao de IP e mismatch Spot/Futures exigem acoes diferentes e nao devem inativar a credencial como se fosse key invalida.

### 3. WebSocket orderbook
- O provider tratava apenas leitura binaria e dependia do `heartbeat` do `aiohttp`.
- Havia comportamento inseguro de parser com `print()` e `exit(-1)`.
- O sistema degradava para polling, mas sem distinguir claramente stale, decode error, fechamento de socket ou falha de heartbeat.

## Decisoes tecnicas adotadas
- Centralizar a politica MEXC em `utils/mexc_support.py`.
- Tratar `recvWindow=60000` como teto operacional fixo desta integracao.
- Registrar logs estruturados com:
  - contexto (`credentials_test`, `client_factory`, `exchange_hub`, `auth_classifier`)
  - operacao
  - categoria
  - `recvWindow`
  - `timeDifferenceMs`
  - horario UTC local
  - bucket UTC por hora
- Expandir o payload de teste de credencial com `diagnostics`, sem quebrar compatibilidade.
- Em runtime, pausar credencial apenas quando a classificacao da MEXC apontar auth real.
- Implementar heartbeat ativo no WS com ping frame + tentativa de JSON ping a cada 20s.
- Substituir falha fatal de protobuf por excecao controlada e fallback.

## Alternativas descartadas
- Aumentar `recvWindow` acima de `60000`: descartado porque o suporte informou `60000` como limite maximo.
- Tratar qualquer erro com palavra `auth` como inativacao de credencial: descartado por gerar falso positivo em casos de permissao.
- Manter somente `heartbeat=20` do `aiohttp`: descartado por nao dar visibilidade nem controle suficiente sobre stream stale.
- Remover o fallback para polling: descartado porque o orderbook precisa continuar operacional mesmo durante degradacao do WS.

## Impacto esperado
- Menos falso `AUTH_FAILED` para chaves MEXC.
- Melhor triagem entre problema de assinatura, permissao, IP e modo de conta.
- Evidencia concreta para responder ao suporte sobre horario UTC e offset observado.
- Recuperacao mais previsivel do WS quando o stream fica stale sem encerrar a conexao.

## Limites conhecidos
- A interpretacao final de mensagens MEXC ainda depende do texto retornado pela exchange/CCXT.
- O formato de heartbeat aceito pela MEXC nao veio detalhado pelo suporte; por isso o cliente envia ping frame e tenta JSON ping.
- O sistema continua orientado a Spot; qualquer uso de chaves Futures continua fora do escopo.

## Checklist operacional
- Confirmar que a API key esta configurada para Spot.
- Habilitar permissoes de leitura de conta/saldo e consulta de ordens.
- Se a operacao exigir, habilitar permissao de trade Spot.
- Revisar whitelist de IP da key e incluir o IP do servidor.
- Em erro de timestamp, verificar horario da maquina e comparar com `GET /api/v3/time`.
- Em erro privado consistente, conferir se a key nao foi criada para Futures.

## Novas configuracoes relevantes
- `MEXC_WS_HEARTBEAT_MS`
- `MEXC_WS_HEARTBEAT_TIMEOUT_MS`

Ambas possuem fallback para os valores globais atuais quando nao forem definidas.

## Validacao executada
- Suite focada:
  - `tests/test_exchange_credentials_api.py`
  - `tests/test_exchange_client_manager.py`
  - `tests/test_market_data.py`
- Resultado em 2026-04-09: `20 passed`.
