# Relatorio de Sistemas Necessarios para Teste e Continuidade

Data: 2026-04-07
Projeto: TradingBot / Crypto
Repositorio remoto: https://github.com/Dev-RuiDiniz/Crypto

## 1) Sistema operacional suportado
- Windows 11 64 bits (validado neste ambiente)
- Tambem pode rodar em Linux/macOS para backend, desde que atendidos os requisitos abaixo

## 2) Ferramentas obrigatorias
- Git (clone, pull, push)
- Python 3.11+
- Node.js 18+ (recomendado LTS)
- npm (instalado junto com Node.js)

## 3) Dependencias Python do projeto
Instalar via:
```bash
pip install -r requirements.txt
```
Pacotes principais em `requirements.txt`:
- ccxt==4.3.92
- aiohttp==3.10.8
- tenacity==8.2.3
- Flask==3.0.3
- pytz==2024.2
- colorama==0.4.6
- cryptography==44.0.1
- protobuf

## 4) Dependencias frontend/electron
Arquivo: `frontend/electron/package.json`
- electron ^31.7.7
- electron-builder ^26.0.12

Instalacao:
```bash
cd frontend/electron
npm ci
```

## 5) Acessos necessarios
- Acesso ao repositorio GitHub: `Dev-RuiDiniz/Crypto` (permissao de leitura/escrita para equipe)
- Chaves de API das exchanges (somente permissao de trade; sem withdraw)
- Variavel de ambiente obrigatoria:
  - `EXCHANGE_CREDENTIALS_MASTER_KEY`
- Variavel opcional:
  - `TRADINGBOT_TENANT_ID`

## 6) Persistencia e dados
- Banco: SQLite local
- Caminho padrao: `./data/state.db`
- O schema e atualizado na inicializacao do `StateStore`

## 7) Comandos de teste/execucao
Backend + worker:
```bash
python run_arbit.py
```

Worker isolado:
```bash
python bot.py --config config.txt
```

Windows launcher:
```bat
EXECUTAR_TRADINGBOT.bat
```

## 8) Versoes validadas neste ambiente
- OS: Windows 11 Pro 64 bits (10.0.26200)
- Git: 2.53.0.windows.1
- Python: 3.11.0
- Node.js: v24.14.0
- npm: 11.9.0

## 9) Observacoes para continuidade
- `node_modules`, caches, venv e builds nao devem ser versionados.
- Segredos devem ser mantidos em variaveis de ambiente e/ou cofre seguro.
- Recomendado validar primeiro em modo paper antes de live.