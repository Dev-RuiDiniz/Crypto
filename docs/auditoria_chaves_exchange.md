# Auditoria Técnica — Gestão de Chaves de Exchange

Data: 2026-02-17 16:17:05Z
Escopo: repositório `/workspace/Crypto`
Método: análise estática de código + inspeção de schema SQLite local, sem suposições externas.

## 1) Resumo executivo

**Status geral: 🔴 INSEGURO**.

Principais motivos:
- **🔴 CRÍTICO**: há chaves/segredos de exchanges e credenciais MB v4 em **texto puro** dentro de `config.txt` versionado no repositório. Evidências: `/workspace/Crypto/config.txt:95-97`, `:103-105`, `:111-113`, `:86-87`.
- Carregamento de credenciais ocorre por `ConfigParser` direto do `config.txt` (sem criptografia, sem secret manager). Evidências: `/workspace/Crypto/bot.py:43-59`, `/workspace/Crypto/exchanges/exchanges_client.py:231-237`, `/workspace/Crypto/exchanges/adapters.py:316-319`.
- Não há função de criptografia/descriptografia para credenciais no fluxo de exchanges. (Busca por `encrypt|decrypt` não retornou implementação de proteção de chaves no runtime.)
- Não há suporte a multiusuário de credenciais por conta/tenant: configuração de exchange é global por seção `EXCHANGES.<nome>`. Evidências: `/workspace/Crypto/exchanges/exchanges_client.py:166-174`, `/workspace/Crypto/exchanges/exchanges_client.py:231-237`.

---

## 2) Tabela “Existe x Falta”

| Controle | Existe | Evidência | Falta / Gap |
|---|---|---|---|
| Armazenamento de chave em arquivo | ✅ | `config.txt` com `api_key/api_secret/password/mbv4_*` | — |
| Chave criptografada em banco | ❌ | SQLite com tabelas operacionais/config sem colunas de segredo; código não persiste chaves em DB | Criptografia em repouso + KMS/secret store |
| Secret manager (Vault, AWS SM etc.) | ❌ | Sem integração no código; sem loader dedicado | Implementar provider de segredos |
| Leitura por variável de ambiente para API key | ❌ (para exchanges) | `os.getenv` é usado para logs/path, não para `API_KEY/API_SECRET` | Carregar credenciais por env/secret manager |
| Mascaramento de logs de segredo | 🟨 Parcial | Não vi log explícito de `api_key/api_secret`; porém erros podem incluir payloads externos | Redaction central e policy de logging |
| Retorno de chave em response da API | ✅ (não identificado) | `GET /api/config` retorna grupos globais/boot/log/risk/pairs/router sem seção `EXCHANGES` | Manter teste automático anti-vazamento |
| Rotação de chave | ❌ | Não há mecanismo/endpoint específico para rotação segura | Rotação com versionamento + rollout |
| Auditoria de alteração | 🟨 Parcial | `config_version` audita mudanças de `config_pairs` e `bot_global_config` | Alterações em `config.txt` (onde estão chaves) não têm trilha dedicada |
| Reload dinâmico das chaves sem restart | ❌ | `ExchangeHub` é criado no boot com `cfg` estático | Re-instanciar adapters em hot-reload seguro |

---

## 3) Objetivo 1 — Onde as chaves estão armazenadas

### Encontrado
1. **Arquivo INI (`config.txt`)** — principal local de segredos:
   - Mercado Bitcoin v4 login/senha: `/workspace/Crypto/config.txt:86-87`
   - NovaDAX `api_key/api_secret`: `/workspace/Crypto/config.txt:95-97`
   - Gate `api_key/api_secret`: `/workspace/Crypto/config.txt:103-105`
   - MEXC `api_key/api_secret`: `/workspace/Crypto/config.txt:111-113`
2. **Em memória do processo** após leitura do INI:
   - `ConfigParser` carregado no boot do worker: `/workspace/Crypto/bot.py:43-59`, `/workspace/Crypto/bot.py:278-281`
   - Injeção em CCXT (`apiKey`, `secret`, `password`): `/workspace/Crypto/exchanges/exchanges_client.py:231-237`, `/workspace/Crypto/exchanges/exchanges_client.py:261-265`
   - MB v4 (`MBV4_LOGIN`, `MBV4_PASSWORD`, `MBV4_BEARER_TOKEN`): `/workspace/Crypto/exchanges/adapters.py:316-319`, `/workspace/Crypto/exchanges/adapters.py:382-387`

### Não encontrado
- `.env` / `load_dotenv`: não encontrado no código.
- `appsettings*.json`: inexistente no repositório.
- Secret manager dedicado: inexistente no código.
- Hardcode direto em constantes Python para chaves de exchange: não encontrado (o hardcode está no arquivo de configuração versionado).

---

## 4) Objetivo 2 — Como são carregadas

### Fluxo de carga de credenciais
1. **Worker (`bot.py`)** lê `config.txt` via `ConfigParser` no startup. (`load_config`)  
   Evidência: `/workspace/Crypto/bot.py:43-59`, `/workspace/Crypto/bot.py:278-281`.
2. **`ExchangeHub`** recebe `cfg` e monta auth params por exchange (`API_KEY`, `API_SECRET`, `PASSWORD`).  
   Evidência: `/workspace/Crypto/exchanges/exchanges_client.py:79-83`, `:231-237`.
3. **CCXT exchange client** é instanciado com esses params.  
   Evidência: `/workspace/Crypto/exchanges/exchanges_client.py:261-267`.
4. **MB v4 adapter** lê login/senha/token da seção `EXCHANGES.mercadobitcoin` e gera header `Authorization: Bearer ...`.  
   Evidência: `/workspace/Crypto/exchanges/adapters.py:311-319`, `:382-387`.

### Padrão arquitetural de carga
- Não há DI container formal; é injeção manual por construtor de objetos no boot do bot.  
  Evidência: `/workspace/Crypto/bot.py:327`, `:448-455`.
- Não há leitura por request de credencial para exchanges; credencial é carregada uma vez no boot do worker.

---

## 5) Objetivo 3 — Verificação de segurança

### 5.1 Criptografia no banco
- **Não**: não foi identificado armazenamento de credenciais no SQLite nem criptografia de segredo.
- Tabelas existentes no `state.db` local: `event_log`, `fills`, `orders` (sem tabelas de secret).
- Código de schema também não modela storage de API key de exchange.

### 5.2 Função de criptografia/descriptografia
- **Não encontrada** para fluxo de credenciais de exchange.
- Chaves são lidas como texto e passadas para clients.

### 5.3 Rotação
- **Não há** mecanismo explícito de rotação de chaves de exchange.
- Há versionamento de configurações de estratégia/risco (`config_version`) em DB, mas não rotação de credenciais.
  Evidência: `/workspace/Crypto/api/handlers.py:961-966`, `:1060-1065`.

### 5.4 Auditoria de alteração
- **Parcial**:
  - Existe trilha de versão para `config_pairs` e `bot_global_config` (DB).
  - Alterações de `config.txt` (onde as chaves estão) não atualizam `config_version` neste endpoint.
  - `update_config` grava INI e retorna sucesso sem bump de versão. Evidência: `/workspace/Crypto/api/handlers.py:857-863`.

### 5.5 Logs
- Não encontrei log direto de `api_key/api_secret`.
- Porém há riscos de vazamento indireto:
  - Erros podem propagar payload bruto em exceções MB v4 (`authorize falhou ... {data}`). Evidência: `/workspace/Crypto/exchanges/adapters.py:361-363`.
  - Logs de contexto operacional podem incluir IDs de conta (`accountId`). Evidência: `/workspace/Crypto/exchanges/adapters.py:466`.

### 5.6 Resposta de API expondo chave
- **Não identificado** no endpoint principal de config:
  - `GET /api/config` retorna campos globais e de operação, sem seção `EXCHANGES`. Evidência: `/workspace/Crypto/api/server.py:202-208`, `/workspace/Crypto/api/handlers.py:656-672`.
- Portanto, **não foi encontrado retorno de chave em API response** nesta auditoria estática.

### 5.7 Permissão de withdraw
- **Não verificável por código atual**: não há validação programática de escopo/permissão de API key (trade-only vs withdraw).
- O sistema assume credenciais válidas e tenta operar.

---

## 6) Objetivo 4 — Atualização dinâmica

### Alterar chave no banco reflete sem restart?
- **Não aplicável diretamente**, pois credenciais de exchange **não estão no banco** (estão em `config.txt`).

### Alterar chave no `config.txt` reflete sem restart?
- **Não** para conexões já instanciadas:
  - `ExchangeHub` é criado no boot e conecta exchanges uma vez. Evidência: `/workspace/Crypto/bot.py:327-330`.
  - Não há rotina de recarregar `config.txt` e re-instanciar `ExchangeHub` em runtime.

### Cache Redis / invalidação
- **Não encontrado** uso de Redis para credenciais/config.

### Worker carrega chave por job ou no boot?
- **No boot** (carga inicial do `cfg`), não por job/request.

---

## 7) Passo obrigatório 1 — Busca por termos e arquivos encontrados

Comando base usado (entre outros):
- `rg -n "API_KEY|API_SECRET|SECRET_KEY|BINANCE|MEXC|BYBIT|get_api_key|load_dotenv|os.getenv|settings.|config.|exchange_adapter" .`

### Resultado consolidado (somente arquivos relevantes ao fluxo de chave)

1. `/workspace/Crypto/config.txt`
   - Trechos: `EXCHANGES.*` com `api_key`, `api_secret`, `mbv4_login`, `mbv4_password`.
   - Função: origem primária das credenciais.

2. `/workspace/Crypto/bot.py`
   - Trechos: `load_config`, `cfg = load_config(cfg_path)`, criação de `ExchangeHub(cfg)`.
   - Função: carrega config no startup e injeta no worker.

3. `/workspace/Crypto/exchanges/exchanges_client.py`
   - Trechos: `_build_auth_params` lendo `API_KEY/API_SECRET/PASSWORD`; instanciação CCXT com credenciais.
   - Função: efetivamente entrega segredo ao cliente de exchange.

4. `/workspace/Crypto/exchanges/adapters.py`
   - Trechos: leitura MBV4 (`MBV4_LOGIN`, `MBV4_PASSWORD`, `MBV4_BEARER_TOKEN`), geração de `Authorization`.
   - Função: autenticação privada Mercado Bitcoin v4.

5. `/workspace/Crypto/core/order_router.py`
   - Trechos: `_mb_has_legacy_keys()` lê `API_KEY/API_SECRET` para fallback CCXT no MB.
   - Função: usa presença de chaves para decidir fallback de execução.

6. `/workspace/Crypto/core/order_manager.py`
   - Trecho: mensagem de erro citando exigência de `API_KEY/SECRET` no config.
   - Função: evidencia dependência operacional de credenciais no INI.

7. `/workspace/Crypto/api/handlers.py` e `/workspace/Crypto/api/server.py`
   - Trechos: GET/POST `/api/config`, leitura/escrita de `config.txt`.
   - Função: dashboard altera configuração operacional; não retorna seção de credenciais.

### Termos sem ocorrência relevante no core auditado
- `SECRET_KEY`: sem ocorrência.
- `BINANCE`: sem ocorrência.
- `BYBIT`: sem ocorrência.
- `get_api_key`: sem ocorrência.
- `load_dotenv`: sem ocorrência.
- `settings.`: sem ocorrência útil.
- `exchange_adapter`: sem ocorrência literal (há módulo `exchanges/adapters.py`).

---

## 8) Passo obrigatório 2 — Mapeamento do fluxo completo

## Dashboard → API → Banco → Worker → Exchange Adapter

1. **Dashboard** chama endpoints `/api/config`, `/api/bot-config`, `/api/bot-global-config`.
   - Evidência: rotas em `/workspace/Crypto/api/server.py:202-227`.

2. **API**:
   - `/api/config` lê/escreve `config.txt` (arquivo). Evidência: `/workspace/Crypto/api/handlers.py:494`, `:684`, `:857-863`.
   - `/api/bot-config` e `/api/bot-global-config` escrevem no SQLite e incrementam `config_version`. Evidência: `/workspace/Crypto/api/handlers.py:911-972`, `:1024-1071`.

3. **Banco (SQLite)**:
   - Guarda parâmetros de operação por par/global e metadados de versão/runtime.
   - Não guarda credenciais de exchange.

4. **Worker**:
   - Sobe com `cfg` carregado do arquivo (`config.txt`) e cria `ExchangeHub(cfg)`. Evidência: `/workspace/Crypto/bot.py:280-281`, `:327-330`.
   - Recarrega configs de DB por `config_version` no monitor (pares e globais), não credenciais da exchange. Evidência: `/workspace/Crypto/core/monitors.py:391-421`.

5. **Exchange Adapter**:
   - `ExchangeHub` injeta `apiKey/secret/password` no CCXT.
   - `MBV4Adapter` usa token/login/senha para endpoints privados.

### Onde a chave entra no fluxo?
- Entra em `config.txt` (`EXCHANGES.*`) e é lida no startup do worker.

### Onde é usada?
- Na criação dos clients de exchange (CCXT e MB v4 private API).

### Onde pode vazar?
- Repositório/host com `config.txt` em texto puro.
- Logs de exceção com payload bruto (cenários de erro MB v4).
- Backups/artefatos que incluam `config.txt`.

---

## 9) Passo obrigatório 3 — Checklist de segurança solicitado

- Chave criptografada no banco: **NÃO**.
- Existe função de criptografia: **NÃO** (para credenciais de exchange).
- Existe rotação de chave: **NÃO**.
- Existe auditoria de alteração: **PARCIAL** (apenas configs em DB, não secrets em arquivo).
- Logs mascaram chave: **NÃO há mecanismo explícito de masking central**.
- Permissão de withdraw ativada/desativada: **NÃO há verificação explícita em código**.

---

## 10) Passo obrigatório 4 — Atualização dinâmica

- Alterar chave no banco reflete sem restart: **N/A (chaves não estão no banco)**.
- Existe cache Redis: **NÃO**.
- Existe invalidação de cache de chave: **NÃO**.
- Worker carrega chave por job ou no boot: **NO BOOT**.

---

## 11) Riscos críticos encontrados

1. **🔴 CRÍTICO — Segredos reais em texto puro no repositório (`config.txt`)**.
2. **🔴 CRÍTICO — Arquitetura sem secret manager/criptografia para credenciais**.
3. **🟠 ALTO — Sem rotação e sem trilha de auditoria dedicada para mudança de credenciais**.
4. **🟠 ALTO — Mudança de credencial depende de restart/recriação de clients**.

---

## 12) Recomendações técnicas

1. **Remover segredos do `config.txt` imediatamente** (usar `config.template.txt` sem segredos).
2. **Introduzir Secret Provider**:
   - MVP: variáveis de ambiente por exchange (`EX_<EXCHANGE>_API_KEY`, etc.).
   - Produção: Vault/AWS Secrets Manager/GCP Secret Manager.
3. **Criptografia em repouso** para qualquer credencial persistida (se optarem por DB):
   - envelope encryption (KMS) + rotação periódica.
4. **Mascaramento obrigatório de logs**:
   - filtro global de redaction para padrões de token/chave.
5. **Rotação operacional**:
   - versão de credencial + validade + rollback seguro.
6. **Hot-reload seguro de credenciais**:
   - detectar mudança e recriar apenas clients afetados com reconexão controlada.
7. **Controle de escopo das chaves**:
   - política trade-only, sem withdraw.

---

## 13) Plano de correção em etapas

### Etapa 0 (imediato — 24h)
- Revogar/rotacionar todas as chaves expostas no `config.txt`.
- Purgar histórico sensível (quando aplicável) e invalidar artefatos distribuídos.

### Etapa 1 (curto prazo — 1 sprint)
- Externalizar segredos para env/secrets manager.
- Criar `config.template.txt` e bloquear commit de segredo (`pre-commit` + scanner).
- Adicionar redaction de logs.

### Etapa 2 (médio prazo — 2 sprints)
- Introduzir serviço de credenciais com versionamento e auditoria.
- Implementar hot-reload/reconnect de adapters por exchange.

### Etapa 3 (produção contínua)
- Rotação automática + monitoramento de uso anômalo.
- Testes de segurança (SAST + secret scanning + testes de vazamento em API).

---

## 14) Suporte a multiusuário / multiexchange / multipares

- **Múltiplos usuários com chaves diferentes**: **NÃO** (modelo global único de `EXCHANGES.*`).
- **Múltiplas exchanges simultâneas**: **SIM** (`_discover_enabled` + `connect_all`).
- **Múltiplos pares por exchange**: **SIM** (`PAIRS.LIST` + mapeamento `SYMBOLS`).

Evidências:
- Exchanges múltiplas: `/workspace/Crypto/exchanges/exchanges_client.py:166-174`, `:241-252`.
- Pares múltiplos: `/workspace/Crypto/config.txt:48`, `/workspace/Crypto/exchanges/exchanges_client.py:59-62`, `:176-204`.

---

## 15) Nível de maturidade atual

**Maturidade: MVP (não pronto para produção segura com credenciais reais).**

Justificativa:
- Segredos em arquivo texto versionado.
- Sem secret manager, sem criptografia de credencial, sem rotação robusta.
- Sem modelo multi-tenant de credenciais.
