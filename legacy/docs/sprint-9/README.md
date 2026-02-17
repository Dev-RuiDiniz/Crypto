# Sprint 9 — Alertas Externos

## Arquitetura

A sprint introduz `NotificationService` centralizado (`core/notification_service.py`) com:
- filtro por tenant/evento/severidade;
- rate-limit por `(tenantId,eventType)`;
- deduplicação por fingerprint do payload na janela configurável;
- canais pluggáveis (`EmailChannel`, `WebhookChannel`);
- execução **não bloqueante** via `notify_nowait`.

## Eventos suportados

- `ORDER_EXECUTED`
- `ARBITRAGE_EXECUTED`
- `AUTH_FAILED`
- `WS_DEGRADED`
- `KILL_SWITCH_ACTIVATED`

Severidades:
- `INFO`
- `IMPORTANT`
- `ERROR`

Payload mínimo esperado:
- `symbol`
- `exchange`
- `amount`
- `price`
- `reason`
- `timestamp`

## Configuração SMTP

Variáveis de ambiente:
- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USER`
- `SMTP_PASS`
- `SMTP_FROM`
- opcional: `SMTP_TIMEOUT_SEC`

Implementação usa TLS (`starttls`) e **não** loga credenciais.

## Configuração Webhook (WhatsApp opcional)

- Canal inicial via webhook genérico.
- Timeout configurável: `WEBHOOK_TIMEOUT_SEC`
- Retry com backoff simples: `WEBHOOK_MAX_RETRIES`
- URL de webhook é persistida criptografada em `notification_settings.webhook_url`.

Payload padrão do webhook:
```json
{
  "eventType": "ORDER_EXECUTED",
  "severity": "INFO",
  "message": "...",
  "timestamp": "2026-01-01T00:00:00Z"
}
```

## Rate limit

- Chave: `(tenantId,eventType)`
- Default: máximo 5 eventos por 60s
- Deduplicação de payload idêntico dentro da mesma janela
- Log estruturado de bloqueio: `NOTIFICATION_RATE_LIMITED`

Env vars:
- `NOTIFICATION_RATE_WINDOW_SEC`
- `NOTIFICATION_RATE_MAX`

## Endpoints

- `GET /api/tenants/{tenantId}/notifications/settings`
- `PUT /api/tenants/{tenantId}/notifications/settings`
- `POST /api/tenants/{tenantId}/notifications/test`

RBAC:
- `ADMIN`: leitura + edição + teste
- `VIEWER`: apenas leitura

## Frontend

Nova aba em **Configurações → Notificações**:
- toggle Email + múltiplos destinatários;
- toggle Webhook + URL com mostrar/ocultar;
- seleção de eventos;
- severidade mínima;
- botões de teste (Email/WhatsApp).

## Boas práticas de segurança

- Nunca versionar credenciais SMTP.
- Não logar URL completa de webhook nem segredos.
- Manter `EXCHANGE_CREDENTIALS_MASTER_KEY` seguro para criptografia de URL.
- Em modo `PAPER`, envio é simulado (`NOTIFICATION_SENT ... result=SIMULATED`).
