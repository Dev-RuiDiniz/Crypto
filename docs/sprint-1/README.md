# Sprint 1 — Multi-tenant + Cofre + Remoção de credenciais do config

## O que mudou
- Worker deixa de usar `config.txt` como fonte de verdade para credenciais de exchange.
- Introduzidas tabelas: `tenants`, `exchange_credentials`, `audit_logs`.
- Adicionado cofre com criptografia AES-256-GCM para credenciais.
- Adicionada auditoria de escrita (sem segredos em metadata).
- Adicionado redaction no logger.

## Como aplicar schema/migrations
- O projeto usa migração por bootstrap no `StateStore`.
- Ao iniciar o worker (`python -m bot ...`), o schema é garantido automaticamente.

## Variáveis de ambiente
- `EXCHANGE_CREDENTIALS_MASTER_KEY` (obrigatória para cofre; 32 bytes em hex/base64).
- `TRADINGBOT_TENANT_ID` (opcional, default `default`).

## Como o worker busca credenciais agora
- Chave de busca: `tenant_id + exchange` em `exchange_credentials` com `status='ACTIVE'`.
- Se não existir credencial ativa: erro explícito e logado, sem fallback para `config.txt`.

## Como validar que `config.txt` não é mais usado para credenciais
1. Deixe `api_key/api_secret/password` em branco no `config.txt`.
2. Inicie worker sem registro no cofre: deve falhar com erro de credenciais ausentes.
3. Cadastre credencial criptografada no cofre e reinicie: conexão deve prosseguir.

## Observação
- `config.template.txt` é apenas template legado de parâmetros gerais e **não** deve receber segredos em produção.
