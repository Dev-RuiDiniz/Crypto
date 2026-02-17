# Como usar o TradingBot (Usuário Final)

## 1) Instalação passo a passo (leigo)

1. Dê duplo clique em `TradingBotSetup.exe`.
2. Clique em **Avançar** até concluir.
3. Se quiser, marque **Criar atalho na Área de Trabalho**.
4. No fim da instalação, marque **Executar TradingBot** e finalize.

## 2) Abrir o bot e localizar o dashboard

- Abra pelo **Menu Iniciar > TradingBot** (ou atalho).
- O sistema inicia localmente e abre o dashboard no navegador.
- Se não abrir sozinho, acesse:
  - `http://127.0.0.1:8000`
  - se não funcionar, abra `%LOCALAPPDATA%\TradingBot\logs\app.log` e veja a porta escolhida.

## 3) Configuração Global (modo, kill switch e limites)

No dashboard, entre em **Config do Bot (DB)**, seção **Config Global (DB)**:

- **Mode**
  - `PAPER`: simulação.
  - `LIVE`: ordens reais.
- **Loop interval (ms)**
  - frequência de ciclo do worker.
- **Kill switch**
  - quando ativado, o ciclo não envia ordens.
- **Max positions**
  - limite de posições por par/exchange (controle de risco).
- **Max daily loss**
  - limite de perda diária (valor numérico).

Clique em **Salvar**.

## 4) Configuração por Par (enabled, risk%, strategy)

Na seção **Config por Par (DB)**:

- **Pair**: ex. `BTC/USDT`.
- **Enabled**: habilita/desabilita o par.
- **Strategy**: atualmente `StrategySpread`.
- **Risk %**: percentual de risco para sizing.
- **Max daily loss**: limite por par.

Clique em **Salvar** na linha do par.

## 5) Verificar “Aplicado às …”

No topo da tela (Status de Aplicação):

- Veja `Config do banco: vX`.
- Veja `Worker aplicou: vY`.
- O status esperado é: **“Aplicado às HH:MM:SS”**.
- Se aparecer “Aplicando...”, aguarde 1–2 ciclos.

## 6) Logs — onde achar e como enviar para suporte

Pasta de logs:
- `%LOCALAPPDATA%\TradingBot\logs\`

Arquivos principais:
- `app.log` (launcher)
- `api.log` (API)
- `worker.log` (execução do bot)

Para suporte:
1. Feche o TradingBot.
2. Compacte a pasta `logs` em `.zip`.
3. Envie o `.zip` e informe horário do problema.

## 7) Reset/limpeza segura

> Use apenas quando orientado por suporte.

1. Pare o bot (feche janela/processo).
2. Faça backup de `%LOCALAPPDATA%\TradingBot\data\state.db`.
3. Se necessário, apague `%LOCALAPPDATA%\TradingBot\data\`.
4. Abra o bot novamente (o banco será recriado).

