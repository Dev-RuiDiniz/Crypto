# Sprint 1 — Segurança de Credenciais

## Criptografia em repouso
- Algoritmo: **AES-256-GCM**.
- Chave mestra: variável `EXCHANGE_CREDENTIALS_MASTER_KEY`.
- Formato persistido: `base64(nonce):base64(ciphertext):base64(tag)`.
- Nonce: 12 bytes randômicos por criptografia.

## Envelope encryption (MVP)
- MVP usa chave mestra única por ambiente.
- Evolução planejada: substituir loader de chave por KMS/HSM mantendo interface de `security/crypto.py`.

## Redaction
- `utils/logger.py` aplica filtro de redaction em console e arquivo.
- Campos sensíveis redigidos: `apiKey`, `apiSecret`, `passphrase`, `masterKey`, `token`, `password` (incluindo variantes).

## Regras operacionais
- Segredos descriptografados apenas em memória no momento de instanciar client.
- Nenhum segredo em logs, metadata de auditoria ou mensagens de erro.
