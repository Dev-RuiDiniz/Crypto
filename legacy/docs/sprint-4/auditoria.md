# Sprint 4 — Auditoria técnica (Worker + credenciais de exchange)

## 1) Mapeamento do Worker

| Item | Status | Evidência | Reaproveitamento |
|---|---|---|---|
| Instanciação de client de exchange | **Existe** | `ExchangeHub` instancia clients CCXT por exchange habilitada (`connect_all`, `_instantiate_exchange`). | Reaproveitar `ExchangeHub` como ponto único de acesso e encapsular rotação nele. |
| Loop por par / scheduler | **Existe** | `MainMonitor.run()` executa loop contínuo, aplica config e processa `pair` por ciclo. | Inserir checagem de versão de credencial no início do ciclo. |
| Multi-par | **Existe** | `for pair in self.pairs` no monitor, com carga dinâmica de pares/config. | Reaproveitar fluxo de ciclo atual sem criar threads extras. |
| Pontos críticos de ordem | **Existe** | `OrderRouter._create_limit_order_safe`, `ExchangeHub.create_limit_order`, `cancel_order`. | Introduzir lock por `(tenantId, exchange)` e anti-duplicidade mínima antes do submit. |

## 2) Mecanismos existentes

| Mecanismo | Status | Evidência | Observação |
|---|---|---|---|
| Cache de instâncias | **Parcial** | `ExchangeHub.exchanges` mantém instâncias em memória, sem metadados/versionamento. | Evoluir para cache estruturado com `version`, `state`, `credentialId`. |
| Locks/mutex | **Não existe** | Não havia mutex explícito por tenant+exchange nas rotas críticas. | Implementar mutex de rotação + lock curto de operação. |
| Hot reload de config | **Existe** | `MainMonitor._reload_configs_if_needed` já aplica versão de config de runtime. | Reaproveitar modelo “polling por ciclo” para credenciais. |
| Retry/reconexão | **Parcial** | `tenacity` em chamadas privadas da hub (`create/cancel/fetch`). | Manter retry, mas bloquear crash em falha de auth e pausar exchange. |
| Health check por exchange | **Parcial** | Teste de credencial existe na API (`/test`) e heartbeat geral do worker. | Adicionar sinalização operacional por exchange via logs estruturados. |

## 3) Como credenciais são obtidas hoje

- Fonte: DB SQLite (tabela `exchange_credentials`) via `ExchangeCredentialsService`.
- Runtime: `ExchangeHub` já usa `tenant_id` + `exchange` para buscar credenciais ativas.
- Segredos: criptografados em repouso, decriptados no serviço em memória.

## 4) Riscos identificados

1. **Race de rotação e ordem**: sem mutex, rotação poderia competir com `create_order`.
2. **Duplicidade em retry/interleaving**: possibilidade de double-submit no mesmo ciclo.
3. **Auth failure em loop**: sem pausa explícita, erro de autenticação pode gerar ruído contínuo.
4. **Client stale**: client não era rotacionado por `version` sem restart.

## 5) Decisão Sprint 4

- **Estratégia escolhida: polling por ciclo** (simples e segura).
- Motivo: não havia pub/sub/event bus já pronto para credenciais; o worker já possui ciclo contínuo adequado para detecção de mudança de `version`.
