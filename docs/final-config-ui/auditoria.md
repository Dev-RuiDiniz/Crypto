# Auditoria — Configuração 100% via Frontend (sistema em execução)

## 1) Frontend
| Item | Status | Evidência | Gap |
|---|---|---|---|
| Credenciais | Existe | `ExchangesSettings` + `exchange-credentials` API | Nenhum crítico |
| Pairs | Parcial | `BotConfigPanel` permitia pares sem CRUD tenant-aware | Faltavam endpoints REST por tenant/pairId e soft-delete |
| Spread | Parcial | Config via `config.txt` (`[SPREAD]`) | Faltava persistência dedicada no DB e edição por par no fluxo de settings |
| Arbitragem | Parcial | Existia painel MVP e endpoint legado por `pair` | Faltava endpoint tenant/pairId + integração explícita no fluxo único Trading |
| Risco | Parcial | Existia configuração em `config_pairs`/`bot_global_config` | Faltava contrato REST novo (global e por par) tenant-aware |
| Notificações | Existe | `NotificationsSettings` e endpoints tenant | Sem gap estrutural |

## 2) Backend
| Requisito | Status | Gap |
|---|---|---|
| CRUD credentials | Existe | Já cobria RBAC e redaction |
| CRUD pairs | Não existe (novo contrato) | Implementado `/api/tenants/{tenantId}/pairs` |
| Spread por par | Não existe (novo contrato) | Implementado `/pairs/{pairId}/spread` com DB |
| Arbitrage por parId | Parcial | Existia por `pair`; adicionado por `pairId` |
| Risk global + por par | Parcial | Adicionado `/risk` e `/pairs/{pairId}/risk` |
| Notifications settings/test | Existe | Mantido |
| Runtime status por par | Não existe | Implementado `/pairs/{pairId}/runtime-status` |

## 3) Armazenamento atual
- Antes: mistura de `config.txt` + DB para diferentes blocos de configuração.
- Agora: novas configurações operacionais via endpoints REST passam a persistir no SQLite (`trading_pairs`, `pair_spread_config`, `tenant_risk_config`, além de tabelas existentes).

## 4) Hot reload / runtime
- Worker já aplicava reload por versão/config da tabela `config_pairs`.
- Ajuste feito: leitura de spread por par priorizando DB (`pair_spread_config`) com fallback legado para `config.txt`.
- Gap remanescente: parte do legado continua com fallback por arquivo para compatibilidade retroativa.
