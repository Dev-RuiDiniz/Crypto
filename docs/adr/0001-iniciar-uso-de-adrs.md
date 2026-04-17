# 1. Iniciar uso de Registros de Decisão de Arquitetura (ADRs)

* Status: Aceito
* Data: 2026-04-15

## Contexto e Problema

O projeto do Robô de Trading Cripto está crescendo em complexidade. Decisões arquiteturais importantes sobre integrações de exchange, gestão de concorrência, políticas de risco (RiskPolicy) e persistência precisam ser documentadas para que o conhecimento não se perca num código em constante evolução, o que dificulta o entendimento por agentes humanos e inteligências artificiais atuando no código.

## Decisão

Adotaremos os [Architecture Decision Records (ADR)](https://adr.github.io/) para documentar decisões técnicas de significativo impacto arquitetural.
Armazenaremos os arquivos na pasta `docs/adr/`.
Usaremos o formato Markdown baseado no modelo do template localizado em `docs/adr/template.md`.

## Consequências

### Positivas
* Manutenção de um histórico rico das decisões e seus porquês.
* Maior facilidade na integração de novos membros (humanos ou agentes de IA) ao contexto da arquitetura do projeto.
* Decisões ficam próximas do código, facilitando a consulta junto ao versionamento.

### Negativas
* Exige a disciplina da equipe em parar, refletir e escrever o documento para qualquer mudança que impacte sistemas chaves (RiskPolicy, Banco, Circuit Breaker).
