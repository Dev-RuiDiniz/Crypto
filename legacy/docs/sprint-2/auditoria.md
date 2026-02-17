# Sprint 2 — Auditoria pré-implementação

## Status por requisito

| Item | Status | Evidência | Reaproveitamento |
|---|---|---|---|
| Autenticação (`userId`/`tenantId`) | **Não existe** | API Flask pública sem middleware auth em `api/server.py`. | Implementado middleware mínimo via `Authorization: Bearer` (claims) e headers fallback (`X-User-Id`, `X-Tenant-Id`, `X-Roles`). |
| RBAC (ADMIN/VIEWER) | **Não existe** | Ausência de verificação de role por rota. | Implementado controle por role no novo módulo da API de credenciais. |
| Rate limiting | **Não existe** | Sem middleware/guardas de throughput no `api/server.py`. | Criado rate limiter em memória por `tenantId+userId+ip` e cooldown por credencial para `/test`. |
| Swagger/OpenAPI | **Não existe** | Não há `/docs/openapi.yaml` no repositório. | Adicionado contrato manual OpenAPI 3.0 em `docs/openapi.yaml`. |
| Logger estruturado + redaction | **Parcial** | `utils/logger.py` e `security/redaction.py` já redigem campos sensíveis. | Reaproveitado `redact_value` para sanitização de payload no request lifecycle. |
| CorrelationId | **Não existe** | Não havia `X-Correlation-Id` no ciclo request/response. | Middleware em `before_request`/`after_request` no servidor Flask. |
| `ExchangeCredentialsService` | **Existe (parcial p/ Sprint 2)** | Já cria/atualiza e lê credenciais criptografadas por tenant+exchange. | Expandido para CRUD completo por `id`, revoke e auditoria de test. |
| AES-GCM helper | **Existe** | `security/crypto.py` já implementa encrypt/decrypt. | Reaproveitado integralmente. |
| `AuditLogService` | **Existe** | `core/audit_log_service.py` grava ação + metadata redigida. | Reaproveitado em CREATE/UPDATE/REVOKE/TEST. |

## Decisões de design

1. **Resolução de tenant**: `tenantId` da URL deve bater com contexto autenticado (claim/header), senão 403.
2. **Auth mínima compatível com base atual**: como não havia JWT validado no backend, foi adotado parser de claims de bearer token (sem validação criptográfica) + fallback por headers para ambiente local.
3. **Padrão de erro único**: `{error,message,details[],correlationId}` para todos endpoints novos.
4. **`id` de credencial**: o schema atual usa `INTEGER AUTOINCREMENT`; mantido para compatibilidade.
5. **`last4`**: derivado do `apiKey`.
6. **Auditoria de LIST**: **não registrada** para reduzir ruído; CREATE/UPDATE/REVOKE/TEST são obrigatórias e implementadas.
7. **Rate limit**: em memória local do processo (adequado ao runtime atual single-instance); quotas configuradas por rota conforme sprint.
