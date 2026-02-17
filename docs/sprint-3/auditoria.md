# Sprint 3 — Auditoria obrigatória (frontend)

## Inventário (Existe / Parcial / Não existe)

| Item auditado | Status | Evidência | Decisão de reaproveitamento |
|---|---|---|---|
| Rotas do dashboard/menu de configurações | **Parcial** | UI sem React Router; navegação por tabs em `frontend/src/App.js` (Dashboard + Config do Bot). | Reaproveitar padrão de tabs e adicionar **Configurações → Exchanges** no mesmo fluxo local. |
| Tabela (DataTable) | **Parcial** | Não existe DataTable genérico; existe padrão visual de tabela (`.table`, `.table-wrapper`) em `styles/components.css`. | Reaproveitar classes atuais de tabela para metadados de credenciais. |
| Modal/Dialog | **Não existe** | Não há componente modal reutilizável; confirmação atual via `window.confirm` em fluxos existentes. | Implementar modal simples local para Add/Rotate e manter `window.confirm` para revogar. |
| Form lib (formik/react-hook-form/zod/yup) | **Não existe** | Inputs controlados com `useState` no front atual (`BotConfigPanel`). | Manter padrão com `useState` + validações mínimas de formulário. |
| Toast/alert | **Parcial** | Há `toast()` local em `BotConfigPanel` baseado em `window.alert`. | Reaproveitar abordagem atual para feedback de sucesso/erro sem payload sensível. |
| Spinner/loading/empty state | **Existe** | Classes `loading`, `loading-spinner`, `empty-state` e uso no dashboard/componentes. | Reaproveitar nas telas de Exchanges. |
| Confirm dialog | **Parcial** | Padrão com `window.confirm` já aceitável no projeto atual. | Reaproveitar para ação de revogar credencial. |
| Cliente HTTP + interceptors | **Parcial** | Existe wrapper `frontend/src/utils/api.js`, mas sem interceptors formais. | Estender wrapper para headers de auth/correlation e parsing de erro seguro. |
| Auth contexto (`tenantId`) | **Parcial** | Front não tinha contexto formal; backend Sprint 2 aceita headers fallback (`X-Tenant-Id`, `X-Roles`, `X-User-Id`). | **Decisão:** usar `window.env` com fallback `localStorage` para tenant/roles/user, default `tenantId=default`. |
| Auth contexto (`role`) | **Parcial** | Sem guard central no front atual. | Implementar RBAC de tela (ADMIN/VIEWER) usando `X-Roles` do contexto acima. |
| Guards/permissões | **Não existe** | Não há route guard/component guard dedicado. | Implementar guard condicional por ação (esconder Add/Rotate/Revoke/Test para VIEWER). |

## Contrato da API Sprint 2 validado

Endpoints confirmados no backend e na doc Sprint 2:
- `GET /api/tenants/{tenantId}/exchange-credentials`
- `POST /api/tenants/{tenantId}/exchange-credentials`
- `PUT /api/tenants/{tenantId}/exchange-credentials/{id}`
- `DELETE /api/tenants/{tenantId}/exchange-credentials/{id}`
- `POST /api/tenants/{tenantId}/exchange-credentials/{id}/test`

Error model confirmado com `correlationId`:
```json
{
  "error": "VALIDATION_ERROR",
  "message": "Descrição humana curta",
  "details": [{"field": "apiKey", "issue": "too_short"}],
  "correlationId": "..."
}
```

## Observações de segurança para Sprint 3
- Não persistir `apiKey/apiSecret/passphrase` em storage global, query params ou logs.
- Limpar formulário de segredo ao fechar modal e após sucesso.
- Exibir erros amigáveis com `correlationId` sem ecoar payload sensível.
