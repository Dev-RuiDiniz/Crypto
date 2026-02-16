# run_arbit.py
import sys
import threading
import time
import webbrowser
import logging
import os
from pathlib import Path
import runpy

# -----------------------------------
# Logging básico
# -----------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="[RUN] %(asctime)s %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


def get_base_dir() -> Path:
    """
    Em dev: pasta onde está este arquivo.
    No .exe (PyInstaller): pasta onde está o executável.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


BASE_DIR = get_base_dir()
sys.path.insert(0, str(BASE_DIR))  # garante import de api, core, bot, etc.

logger.info(f"BASE_DIR detectado: {BASE_DIR}")


# -----------------------------------
# BOT (core ARBIT) - MELHORADO
# -----------------------------------
def start_bot() -> bool:
    """
    Tenta rodar o bot do jeito mais parecido possível com:
        python bot.py
    
    Retorna True se o bot inicializou com sucesso, False caso contrário.
    """
    try:
        logger.info("Iniciando bot em background...")

        # garante que o bot veja o diretório certo
        os.chdir(BASE_DIR)
        logger.info(f"[BOT] cwd = {Path.cwd()}")

        # Verifica se o bot.py existe
        bot_path = BASE_DIR / "bot.py"
        if not bot_path.exists():
            logger.error(f"[BOT] ❌ Arquivo bot.py não encontrado em {bot_path}")
            logger.error("[BOT] ❌ Verifique a estrutura de pastas do projeto.")
            return False

        # 1) tenta importar bot e chamar main() se existir
        try:
            import bot as bot_mod  # type: ignore

            if hasattr(bot_mod, "main"):
                logger.info("[BOT] Encontrado bot.main(), executando...")
                bot_mod.main()
                logger.info("[BOT] main() retornou (bot finalizou).")
                return True
            else:
                logger.info(
                    "[BOT] bot.main() não encontrado, caindo para run_module..."
                )
        except Exception as e:
            logger.exception(f"[BOT] Falha ao importar bot.main(): {e}")
            logger.warning("[BOT] Usando run_module como fallback...")

        # 2) fallback: rodar módulo como script principal
        sys.argv = ["bot.py"]  # se você costuma passar args, coloque aqui
        logger.info(f"[BOT] Executando run_module('bot', run_name='__main__'), argv={sys.argv}")
        runpy.run_module("bot", run_name="__main__")
        logger.info("[BOT] run_module('bot', '__main__') terminou.")
        return True

    except SystemExit as e:
        exit_code = e.code if hasattr(e, 'code') else 1
        if exit_code == 0:
            logger.info(f"[BOT] Bot finalizado normalmente com exit code {exit_code}")
        else:
            logger.error(f"[BOT] ❌ Bot finalizou com SystemExit (código {exit_code}): {e}")
            return False
    except Exception as e:
        logger.exception(f"[BOT] ❌ Erro crítico ao executar bot.py: {e}")
        return False
    
    return True


# -----------------------------------
# API Flask
# -----------------------------------
def start_api():
    """
    Sobe a API Flask (api/server.py::main)
    """
    try:
        os.chdir(BASE_DIR)
        logger.info(f"[API] cwd = {Path.cwd()}")
        logger.info("[API] Importando api.server...")
        from api import server

        server.main()
    except Exception:
        logger.exception("[API] Erro ao iniciar API Flask")


# -----------------------------------
# Verificação de dependências
# -----------------------------------
def check_dependencies() -> bool:
    """
    Verifica dependências críticas antes de iniciar.
    Retorna True se todas as dependências estão OK.
    """
    required_modules = [
        "aiohttp",
        "ccxt",
        "tenacity",
        "configparser",
        "flask",  # para a API
    ]
    
    missing = []
    for module in required_modules:
        try:
            __import__(module)
            logger.info(f"[CHECK] ✅ {module}")
        except ImportError as e:
            logger.error(f"[CHECK] ❌ {module}: {e}")
            missing.append(module)
    
    if missing:
        logger.error(f"[CHECK] ❌ Faltam dependências: {', '.join(missing)}")
        logger.error("[CHECK] Execute: pip install aiohttp ccxt tenacity flask")
        return False
    
    return True


def check_project_structure() -> bool:
    """
    Verifica a estrutura básica de pastas do projeto.
    """
    required_dirs = [
        BASE_DIR / "api",
        BASE_DIR / "core",
        BASE_DIR / "exchanges",
        BASE_DIR / "utils",
    ]
    
    required_files = [
        BASE_DIR / "bot.py",
        BASE_DIR / "config.txt",
    ]
    
    all_ok = True
    
    for dir_path in required_dirs:
        if dir_path.exists() and dir_path.is_dir():
            logger.info(f"[STRUCT] ✅ Pasta {dir_path.name}/")
        else:
            logger.error(f"[STRUCT] ❌ Pasta ausente: {dir_path.name}/")
            all_ok = False
    
    for file_path in required_files:
        if file_path.exists():
            logger.info(f"[STRUCT] ✅ Arquivo {file_path.name}")
        else:
            logger.warning(f"[STRUCT] ⚠️  Arquivo ausente: {file_path.name}")
            # config.txt pode ser criado depois, não é crítico
            if file_path.name != "config.txt":
                all_ok = False
    
    return all_ok


# -----------------------------------
# MAIN - MELHORADA
# -----------------------------------
def main():
    # garante CWD correto logo no início
    os.chdir(BASE_DIR)
    logger.info(f"[RUN] Iniciando ARBIT, cwd = {Path.cwd()}")
    
    # Verificação preliminar
    logger.info("[RUN] Verificando dependências...")
    if not check_dependencies():
        logger.error("[RUN] ❌ Dependências faltando. Abortando.")
        sys.exit(1)
    
    logger.info("[RUN] Verificando estrutura do projeto...")
    if not check_project_structure():
        logger.warning("[RUN] ⚠️  Estrutura incompleta, mas prosseguindo...")
    
    # Thread do BOT com detecção de falha
    logger.info("[RUN] Iniciando thread do bot...")
    
    # Variável compartilhada para indicar sucesso
    bot_success = threading.Event()
    bot_failed = threading.Event()
    
    def bot_wrapper():
        """Wrapper para detectar se o bot rodou com sucesso"""
        try:
            if start_bot():
                bot_success.set()
                logger.info("[BOT-WRAPPER] ✅ Bot inicializou com sucesso")
            else:
                bot_failed.set()
                logger.error("[BOT-WRAPPER] ❌ Bot falhou na inicialização")
        except Exception as e:
            logger.exception(f"[BOT-WRAPPER] ❌ Exceção não tratada no bot: {e}")
            bot_failed.set()
    
    bot_thread = threading.Thread(target=bot_wrapper, daemon=True, name="BotThread")
    bot_thread.start()
    logger.info("[RUN] Thread do bot iniciada.")
    
    # Aguarda inicialização do bot (tempo limite)
    logger.info("[RUN] Aguardando inicialização do bot (10s)...")
    for i in range(20):  # 20 tentativas de 0.5s = 10s total
        if bot_success.is_set():
            logger.info("[RUN] ✅ Bot inicializado com sucesso!")
            break
        if bot_failed.is_set():
            logger.error("[RUN] ❌ Bot falhou durante inicialização!")
            logger.error("[RUN] ⚠️  API será iniciada, mas o bot não está funcionando.")
            break
        time.sleep(0.5)
    
    # Verifica se a thread está viva
    if not bot_thread.is_alive():
        logger.error("[RUN] ❌ Thread do bot morreu imediatamente!")
        logger.error("[RUN] ⚠️  Verifique logs anteriores para erros.")
    
    # Aguarda um pouco mais para garantir que o bot está rodando
    time.sleep(2.0)
    
    # Verificação final do bot
    if not bot_thread.is_alive() and not bot_failed.is_set():
        logger.error("[RUN] ❌ Thread do bot não está mais ativa após 12 segundos!")
        logger.error("[RUN] ⚠️  O bot pode não estar funcionando.")
    
    # Abre a UI no navegador (só se a API conseguir subir)
    url = "http://127.0.0.1:8000"
    logger.info(f"[RUN] Tentando abrir navegador em {url} em 3 segundos...")
    time.sleep(3.0)
    
    try:
        webbrowser.open(url)
        logger.info(f"[RUN] Navegador aberto em {url}")
    except Exception as e:
        logger.warning(f"[RUN] Falha ao abrir navegador: {e}")
        logger.info(f"[RUN] Acesse manualmente: {url}")
    
    # API na thread principal (bloqueante)
    logger.info("[RUN] Iniciando API Flask...")
    try:
        start_api()
    except Exception as e:
        logger.exception(f"[RUN] ❌ API Flask falhou: {e}")
        logger.info("[RUN] Encerrando sistema...")
        sys.exit(1)


if __name__ == "__main__":
    main()