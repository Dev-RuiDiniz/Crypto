# 2. Adotar fluxo explicito de Travel Rule no Mercado Bitcoin Wallet

* Status: Aceito
* Data: 2026-04-17

## Contexto e Problema

O Mercado Bitcoin comunicou que, a partir de 2026-05-01, saques de criptoativos sem `travel_rule` serao rejeitados e depositos pendentes exigirao envio posterior dessas informacoes para credito em conta. A integracao existente estava focada em trading Spot e nao deixava claro, no codigo, como tratar os endpoints de wallet afetados por essa mudanca regulatoria.

## Direcionadores da Decisao

* Alinhar a integracao com a documentacao oficial mais recente do Mercado Bitcoin v4.
* Evitar ambiguidade entre endpoints de trading e endpoints de wallet.
* Dar suporte explicito a Travel Rule sem quebrar os fluxos atuais de trading.
* Melhorar operabilidade e diagnostico antes da vigencia regulatoria.

## Opcoes Consideradas

* Ignorar o tema porque o bot recomenda chaves sem withdraw.
* Tratar Travel Rule apenas em documentacao externa, sem codigo.
* Implementar suporte explicito a wallet/Travel Rule no adapter do Mercado Bitcoin v4.

## Decisao

Escolhemos implementar suporte explicito a wallet/Travel Rule no adapter do Mercado Bitcoin v4, porque isso reduz risco operacional, aproxima o repo do contrato real da API e organiza melhor a separacao entre trading Spot e operacoes de wallet.

## Consequencias

### Positivas
* O repo passa a refletir o contrato atual de `withdraw`, `list deposits` e `release pending deposit`.
* Validacoes de Travel Rule ficam centralizadas e reutilizaveis.
* O diagnostico local (`MB.py`) e os testes automatizados passam a cobrir os novos endpoints.

### Negativas
* A integracao ganha mais superficie de codigo para manutencao.
* Ainda depende de payloads corretos fornecidos pelo operador para chamadas reais de wallet.
