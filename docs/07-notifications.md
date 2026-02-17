# 07 - Notifications

Canais suportados:
- E-mail SMTP
- Webhook (inclui integração com gateways WhatsApp)

## Segurança
- `webhook_url` é armazenada criptografada no banco.
- Logs aplicam redaction para evitar vazamento de segredo.

## Operação
- Configuração por tenant via API/dashboard.
- Teste manual de canais disponível na interface.
