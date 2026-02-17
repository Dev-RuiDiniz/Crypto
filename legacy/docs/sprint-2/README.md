# Sprint 2 — API de Exchange Credentials

## OpenAPI
- Contrato: `/docs/openapi.yaml`

## RBAC
- `ADMIN`: GET/POST/PUT/DELETE/TEST
- `VIEWER`: apenas GET list

Headers esperados:
- `Authorization: Bearer <jwt>` (claims: `sub`, `tenantId`, `roles`) **ou**
- fallback local: `X-User-Id`, `X-Tenant-Id`, `X-Roles`

## Rate limits
- POST create: **5/min**
- PUT update: **10/min**
- POST test: **10/min** + cooldown **10s** por credencial

## CorrelationId
- API aceita `X-Correlation-Id` e devolve sempre no response header.
- Em erros, também vem no payload `correlationId`.

## Erros
Modelo:
```json
{
  "error": "VALIDATION_ERROR",
  "message": "Descrição humana curta",
  "details": [{"field": "apiKey", "issue": "too_short"}],
  "correlationId": "..."
}
```

## cURL rápido

### Listar
```bash
curl -H "X-User-Id: admin1" -H "X-Tenant-Id: default" -H "X-Roles: ADMIN" \
  http://localhost:8000/api/tenants/default/exchange-credentials
```

### Criar
```bash
curl -X POST http://localhost:8000/api/tenants/default/exchange-credentials \
  -H "Content-Type: application/json" \
  -H "X-User-Id: admin1" -H "X-Tenant-Id: default" -H "X-Roles: ADMIN" \
  -d '{"exchange":"mexc","label":"Conta Principal","apiKey":"abcdefgh1234","apiSecret":"segredo123456","passphrase":null}'
```

### Atualizar/rotacionar
```bash
curl -X PUT http://localhost:8000/api/tenants/default/exchange-credentials/1 \
  -H "Content-Type: application/json" \
  -H "X-User-Id: admin1" -H "X-Tenant-Id: default" -H "X-Roles: ADMIN" \
  -d '{"label":"Conta Nova","apiSecret":"novoSegredo123456"}'
```

### Revogar
```bash
curl -X DELETE http://localhost:8000/api/tenants/default/exchange-credentials/1 \
  -H "X-User-Id: admin1" -H "X-Tenant-Id: default" -H "X-Roles: ADMIN"
```

### Testar conexão
```bash
curl -X POST http://localhost:8000/api/tenants/default/exchange-credentials/1/test \
  -H "X-User-Id: admin1" -H "X-Tenant-Id: default" -H "X-Roles: ADMIN"
```
