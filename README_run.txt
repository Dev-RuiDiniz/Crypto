ARBIT - Bot de Arbitragem (Terminal)

1) Pré-requisitos
   - Python 3.11+ (recomendado)
   - Windows (CMD/PowerShell)
   - Venv existente: .venv313 (na raiz 1ARBIT)
   - Exchanges com API habilitada (coloque as chaves no config.txt)

2) Instalação das dependências (no CMD, na pasta 1ARBIT)
   call ".venv313\Scripts\activate" && pip install -r requirements.txt

3) Configure o arquivo config.txt
   - [GLOBAL] MODE -> use PAPER para testes (não envia ordens reais)
   - USDT_BRL_RATE -> informe a sua cotação manual do USDT
   - [PAIRS] LIST -> ex.: BTC/USDT,ETH/USDT
   - [SPREAD] por par -> ex.: BTC/USDT=0.10 (10%)
   - [STAKE] por par -> FIXO_USDT ou PCT_BALANCE
   - [EXCHANGES.xxx] -> ENABLED=true e credenciais (API_KEY/SECRET)
   - [SYMBOLS] -> mapeamento dos símbolos por exchange/side (já tem um template)
   - [ROUTER] MIN_NOTIONAL_USDT -> valor mínimo por ordem em USDT

4) Rodando o bot (PAPER)
   call ".venv313\Scripts\activate" && python bot.py "config.txt"

5) Logs e dados
   - Logs: .\logs\arbit.log
   - SQLite: .\data\state.db (orders, fills, event_log)
   - CSV: .\data\orders.csv e .\data\fills.csv (se CSV_ENABLE=true)

6) Dicas
   - Comece com MODE=PAPER para validar fluxo e ver se aparecem prints de "MainMonitor iniciado" e criação/cancelamento de ordens simuladas.
   - Ajuste ADJUST_COOLDOWN_SEC e REPRICE_THRESHOLD_BPS para controlar a frequência de reprecificação.
   - Gate/MEXC operam com USDT nativo. Mercado Bitcoin/NovaDAX operam BRL; o bot normaliza para USDT com USDT_BRL_RATE.
   - Se alguma exchange não carregar, verifique o ID ccxt e credenciais (IDs usados: mercadobitcoin=mercado, novadax, gate, mexc).

7) Comandos úteis
   - Ver árvore de arquivos:
     tree /F /A "C:\Users\Alisson\Desktop\CLIENTES DATAPIX\1ARBIT"
   - Ativar venv:
     call ".venv313\Scripts\activate"
   - Sair do venv:
     deactivate
