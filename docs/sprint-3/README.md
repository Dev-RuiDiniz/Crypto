# Sprint 3 — Dashboard de credenciais de Exchanges

## Rota/Navegação
- Navegação via dashboard: **Configurações → Exchanges**.
- Estrutura atual do projeto usa tabs locais (sem React Router), então o caminho lógico da sprint foi implementado dentro da shell do dashboard.

## Fluxos implementados

### 1) Adicionar credencial (ADMIN)
1. Clique em **Adicionar credencial**.
2. Preencha `exchange`, `label`, `apiKey`, `apiSecret` e opcional `passphrase`.
3. Marque a confirmação: **“NÃO habilitei withdraw”**.
4. Salve.

Resultado:
- Chama `POST /api/tenants/{tenantId}/exchange-credentials`.
- Fecha modal, mostra toast e atualiza tabela.

### 2) Rotacionar credencial (ADMIN)
1. Clique em **Rotacionar** na linha desejada.
2. Edite `label`/`status`.
3. Preencha segredos apenas se realmente for rotacionar.
4. Salve.

Resultado:
- Chama `PUT /api/tenants/{tenantId}/exchange-credentials/{id}`.
- Campos de segredo vazios **não** são enviados no payload.

### 3) Testar conexão (ADMIN)
- Botão **Testar** por linha.
- Exibe estado de loading no botão.
- Sucesso: toast com latência.
- Erro: toast amigável com `correlationId` quando disponível.

### 4) Revogar (ADMIN)
- Botão **Revogar** por linha (danger).
- Confirmação obrigatória.
- Chama `DELETE /api/tenants/{tenantId}/exchange-credentials/{id}`.

## Regras de segurança
- Segredos não são persistidos em localStorage/sessionStorage/redux/query string.
- Inputs de segredo usam `type=password` + mostrar/ocultar + `autocomplete="off"`.
- Após sucesso/fechamento de modal, formulário é resetado.
- Em erro, mensagens sanitizadas sem eco de payload sensível.
- Banner visível na página:
  - **Use apenas permissões de TRADE. NÃO habilite WITHDRAW.**

## Permissões (ADMIN / VIEWER)
- Fonte: contexto de auth no front (`window.env` ou fallback localStorage).
- `ADMIN`: vê e executa Add/Rotate/Test/Revoke.
- `VIEWER`: apenas leitura da tabela de metadados.
- Defesa em profundidade: `403` vira mensagem amigável (**Sem permissão**).

## Como validar rapidamente
1. Defina credenciais de contexto no browser (`window.env` ou localStorage):
   - `tenantId`
   - `roles` (`ADMIN` ou `VIEWER`)
2. Acesse **Configurações → Exchanges**.
3. Valide a visibilidade das ações conforme role.
4. Execute os fluxos com API local ativa.
