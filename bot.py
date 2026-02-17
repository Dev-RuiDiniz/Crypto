# bot.py
# ARBIT - Ponto de entrada robusto
# - Lê config.txt (aceita comentários inline ; e #)
# - Inicializa logging e pastas (console humano + arquivo detalhado)
# - Valida imports (falha alto se faltar algo)
# - Conecta exchanges
# - Cancela ordens vivas (BOOT)
# - Instancia estratégia/roteador/gerenciadores
# - Roda o loop principal (MainMonitor)

import os
import sys
import argparse
import configparser
import asyncio
import traceback
from pathlib import Path
from typing import Dict, Any, List, Optional

from utils.logger import configure_logging, get_logger, get_user_logger
from app.version import APP_VERSION

APP_NAME = "ARBIT"
log = get_logger(APP_NAME)         # técnico -> arquivo detalhado
ulog = get_user_logger(APP_NAME)   # humano  -> console

# ---------------- CLI / Config ----------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="ARBIT - Bot de arbitragem multi-exchanges")
    p.add_argument("config", nargs="?", default="config.txt",
                   help="Caminho do arquivo INI (padrão: ./config.txt)")
    p.add_argument("--db-path", default=None, help="Sobrescreve SQLITE_PATH")
    return p.parse_args()


def load_config(path: str) -> configparser.ConfigParser:
    """
    Carrega o config.txt do ARBIT.

    IMPORTANTE:
      - Também é usado pela API (api/handlers.py) para ler e atualizar o mesmo config.
      - Aceita comentários inline (ex.: USDT_BRL_RATE=5.60 ; comentário).
    """
    cfg = configparser.ConfigParser(
        interpolation=None,
        inline_comment_prefixes=(";", "#"),
    )
    read_ok = cfg.read(path, encoding="utf-8")
    if not read_ok:
        print(f"[ERRO] Não foi possível ler o arquivo de configuração: {path}")
        sys.exit(1)
    return cfg


def ensure_directories():
    """Cria diretórios necessários para o funcionamento do bot."""
    dirs = ["./data", "./logs"]
    for dir_path in dirs:
        Path(dir_path).mkdir(parents=True, exist_ok=True)


def setup_logging_from_config(cfg: configparser.ConfigParser):
    """
    Compat + extras:
      [LOG]
      LEVEL=INFO              ; fallback para CONSOLE_LEVEL
      CONSOLE_LEVEL=INFO      ; opcional
      FILE_LEVEL=DEBUG        ; opcional
      FILE=./logs/arbit.log   ; base p/ derivar <base>_detail.txt
      DETAIL_FILE=            ; opcional: caminho do arquivo detalhado
      ROTATE_MB=10
    """
    base_level     = cfg.get("LOG", "LEVEL", fallback="INFO")
    console_level  = cfg.get("LOG", "CONSOLE_LEVEL", fallback=base_level)
    file_level     = cfg.get("LOG", "FILE_LEVEL", fallback="DEBUG")
    filename       = os.getenv("TRADINGBOT_WORKER_LOG_FILE", "").strip() or cfg.get("LOG", "FILE", fallback="./logs/arbit.log")
    detailed_file  = cfg.get("LOG", "DETAIL_FILE", fallback=None)
    rotate_mb      = cfg.getint("LOG", "ROTATE_MB", fallback=10)

    configure_logging(
        level=console_level,
        filename=filename,
        rotate_mb=rotate_mb,
        detailed_filename=detailed_file if detailed_file else None,
        console_level=console_level,
        file_level=file_level,
    )


def config_summary(cfg: configparser.ConfigParser) -> Dict[str, Any]:
    """Resumo da configuração para logs iniciais."""
    pairs = [s.strip() for s in cfg.get("PAIRS", "LIST", fallback="").split(",") if s.strip()]
    
    # Lê parâmetros de rede com fallback para BOOT
    http_timeout = _get_param_with_fallback(cfg, "HTTP_TIMEOUT_SEC", 15, 
                                           fallback_sections=["BOOT"],
                                           fallback_keys=["HTTP_TIMEOUT"])
    max_retries = _get_param_with_fallback(cfg, "MAX_RETRIES", 3,
                                          fallback_sections=["BOOT"])
    retry_backoff = _get_param_with_fallback(cfg, "RETRY_BACKOFF_MS", 400,
                                            fallback_sections=["BOOT"])
    
    return {
        "MODE": cfg.get("GLOBAL", "MODE", fallback="PAPER"),
        "USDT_BRL_RATE": cfg.getfloat("GLOBAL", "USDT_BRL_RATE", fallback=5.50),
        "REF_PRICE": cfg.get("GLOBAL", "REF_PRICE", fallback="MEDIAN"),
        "LOOP_INTERVAL_MS": cfg.getint("GLOBAL", "LOOP_INTERVAL_MS", fallback=1200),
        "PRINT_EVERY_SEC": cfg.getint("GLOBAL", "PRINT_EVERY_SEC", fallback=5),
        "PAIRS": pairs,
        "HEDGE_ON_FILL": cfg.getboolean("HEDGE", "HEDGE_ON_FILL", fallback=False),
        "HTTP_TIMEOUT_SEC": http_timeout,
        "MAX_RETRIES": max_retries,
        "RETRY_BACKOFF_MS": retry_backoff,
    }


def _get_param_with_fallback(
    cfg: configparser.ConfigParser,
    key: str, 
    default: int,
    fallback_sections: Optional[List[str]] = None,
    fallback_keys: Optional[List[str]] = None
) -> int:
    """
    Obtém um parâmetro inteiro com múltiplos fallbacks.
    Compatível com a lógica do ExchangeHub.
    """
    sections_to_try = ["GLOBAL"]
    if fallback_sections:
        sections_to_try.extend(fallback_sections)
        
    keys_to_try = [key]
    if fallback_keys:
        keys_to_try.extend(fallback_keys)
    
    for section in sections_to_try:
        if not cfg.has_section(section):
            continue
            
        for k in keys_to_try:
            try:
                value = cfg.get(section, k)
                if value is not None:
                    return int(value)
            except (configparser.NoOptionError, ValueError):
                continue
    
    return default

# ---------------- Imports críticos (sem placeholders) ----------------

def import_or_die():
    """Verifica se todos os módulos necessários estão disponíveis."""
    required_modules = [
        ("exchanges.exchanges_client", "ExchangeHub"),
        ("core.strategy_spread", "StrategySpread"),
        ("core.order_router", "OrderRouter"),
        ("core.order_manager", "OrderManager"),
        ("core.portfolio", "Portfolio"),
        ("core.state_store", "StateStore"),
        ("core.risk_manager", "RiskManager"),
        ("core.monitors", "MainMonitor"),
    ]
    
    missing_modules = []
    
    for module_name, class_name in required_modules:
        try:
            __import__(module_name)
        except ImportError as e:
            missing_modules.append(f"{module_name} ({e})")
    
    if missing_modules:
        print("\n[ERRO] ❌ Falta de dependências ou módulos corrompidos!")
        print("Módulos ausentes ou com erro de importação:")
        for module in missing_modules:
            print(f"  - {module}")
        print("\nVerifique:")
        print("  1. Estrutura de pastas (api/, core/, exchanges/, utils/)")
        print("  2. Dependências: pip install aiohttp ccxt tenacity")
        print("  3. Arquivos Python corrompidos")
        sys.exit(2)
    
    # Verifica dependências de pacotes
    required_packages = ["aiohttp", "ccxt", "tenacity"]
    missing_packages = []
    
    for package in required_packages:
        try:
            __import__(package)
        except ImportError:
            missing_packages.append(package)
    
    if missing_packages:
        print(f"\n[ERRO] ❌ Pacotes Python faltando: {', '.join(missing_packages)}")
        print(f"Execute: pip install {' '.join(missing_packages)}")
        sys.exit(2)


def get_components(cfg):
    """Importa e retorna todos os componentes necessários."""
    from exchanges.exchanges_client import ExchangeHub
    from core.strategy_spread import StrategySpread
    from core.order_router import OrderRouter
    from core.order_manager import OrderManager
    from core.portfolio import Portfolio
    from core.state_store import StateStore
    from core.risk_manager import RiskManager
    from core.monitors import MainMonitor
    return ExchangeHub, StrategySpread, OrderRouter, OrderManager, Portfolio, StateStore, RiskManager, MainMonitor

# ---------------- Helpers de BOOT ----------------

async def _ccxt_cancel_all_if_supported(ex_hub, targets: Optional[List[str]] = None):
    """
    Primeiro tenta usar cancel_all_orders() da exchange (quando existir).
    Se targets for None, tenta global; senão tenta por símbolo local BUY/SELL.
    """
    for ex_name, ex in ex_hub.exchanges.items():
        if not hasattr(ex, "cancel_all_orders"):
            continue
        try:
            if not targets:
                try:
                    await ex.cancel_all_orders(None)
                except TypeError:
                    await ex.cancel_all_orders()
            else:
                for gp in targets:
                    sym_buy = None
                    try:
                        sym_buy = ex_hub.resolve_symbol_local(ex_name, "BUY", gp)
                        await ex.cancel_all_orders(sym_buy)
                    except Exception:
                        pass
                    try:
                        sym_sell = ex_hub.resolve_symbol_local(ex_name, "SELL", gp)
                        if (sym_buy is None) or (sym_sell != sym_buy):
                            await ex.cancel_all_orders(sym_sell)
                    except Exception:
                        pass
        except Exception as e:
            log.warning(f"[{ex_name}] cancel_all_orders falhou: {e}")


async def _post_cancel_verify(ex_hub, targets: Optional[List[str]] = None) -> Dict[str, Dict[str, int]]:
    """Lista novamente as ordens abertas por exchange para checar se o cancelamento refletiu."""
    summary: Dict[str, Dict[str, int]] = {}
    for ex_name in ex_hub.enabled_ids:
        listed = 0
        errors = 0
        try:
            try:
                opens = await ex_hub.fetch_open_orders(ex_name, global_pair=None)
            except Exception:
                opens = []
                if targets:
                    for p in targets:
                        try:
                            opens.extend(await ex_hub.fetch_open_orders(ex_name, global_pair=p))
                        except Exception:
                            pass
            listed = len(opens)
        except Exception:
            errors += 1
        summary[ex_name] = {"listed": listed, "errors": errors, "cancelled": 0}
    return summary

# ---------------- Main async ----------------

async def async_main(cfg_path: str, db_path_override: Optional[str] = None):
    """Função principal assíncrona do bot."""
    cfg = load_config(cfg_path)
    if db_path_override:
        if "GLOBAL" not in cfg:
            cfg["GLOBAL"] = {}
        cfg["GLOBAL"]["SQLITE_PATH"] = os.path.abspath(db_path_override)
    ensure_directories()
    setup_logging_from_config(cfg)

    resolved_db_path = os.path.abspath(cfg.get("GLOBAL", "SQLITE_PATH", fallback="./data/state.db"))
    log.info("[BOOT] DB_PATH=%s", resolved_db_path)
    log.info("[BOOT] APP_VERSION=%s", APP_VERSION)

    s = config_summary(cfg)

    # Técnico -> arquivo detalhado
    log.info("====================================================")
    log.info(f"{APP_NAME} - Inicializando")
    log.info(f"MODE={s['MODE']}  REF={s['REF_PRICE']}  USDT_BRL_RATE={s['USDT_BRL_RATE']}")
    log.info(f"PAIRS={','.join(s['PAIRS']) if s['PAIRS'] else '(vazio)'}")
    log.info(f"LOOP_INTERVAL_MS={s['LOOP_INTERVAL_MS']}  PRINT_EVERY_SEC={s['PRINT_EVERY_SEC']}")
    log.info(f"HEDGE_ON_FILL={s['HEDGE_ON_FILL']}")
    log.info(f"HTTP_TIMEOUT_SEC={s['HTTP_TIMEOUT_SEC']}  MAX_RETRIES={s['MAX_RETRIES']}  RETRY_BACKOFF_MS={s['RETRY_BACKOFF_MS']}")
    log.info("====================================================")

    # Humano -> console
    ulog.info("====================================================")
    ulog.info(f"Iniciando {APP_NAME} (modo {s['MODE']}).")
    ulog.info(f"Pares: {', '.join(s['PAIRS']) if s['PAIRS'] else '(nenhum)'} | Ref: {s['REF_PRICE']}")
    ulog.info(f"Taxa USDT/BRL usada: {s['USDT_BRL_RATE']:.2f}")
    ulog.info(f"Parâmetros de rede: timeout={s['HTTP_TIMEOUT_SEC']}s, retries={s['MAX_RETRIES']}, backoff={s['RETRY_BACKOFF_MS']}ms")
    ulog.info("Conectando às corretoras...")

    # Garantir imports reais
    import_or_die()
    
    try:
        ExchangeHub, StrategySpread, OrderRouter, OrderManager, Portfolio, StateStore, RiskManager, MainMonitor = get_components(cfg)
    except Exception as e:
        log.error(f"Falha ao importar componentes: {e}")
        ulog.error("❌ Falha ao carregar componentes do bot. Verifique logs detalhados.")
        raise

    # Instâncias principais
    ex_hub = ExchangeHub(cfg)
    try:
        await ex_hub.connect_all()
    except Exception as e:
        log.error(f"Falha ao conectar exchanges: {e}", exc_info=True)
        ulog.error("❌ Falha ao conectar às corretoras. Verifique:")
        ulog.error("  1. Credenciais de API no config.txt")
        ulog.error("  2. Conexão com a internet")
        ulog.error("  3. Se as exchanges estão funcionando")
        raise
    ulog.info(f"✅ Corretoras ativas: {', '.join(ex_hub.enabled_ids) or '(nenhuma)'}")

    # ---------- CANCELAMENTO DE ORDENS NO BOOT ----------

    cancel_on_start = cfg.getboolean("BOOT", "CANCEL_OPEN_ORDERS_ON_START", fallback=False)
    only_cfg_pairs  = cfg.getboolean("BOOT", "CANCEL_ONLY_CONFIGURED_PAIRS", fallback=True)
    dry_run         = cfg.getboolean("BOOT", "CANCEL_DRY_RUN", fallback=False)
    pairs_cfg       = [s.strip() for s in cfg.get("PAIRS", "LIST", fallback="").split(",") if s.strip()]
    targets         = (pairs_cfg if only_cfg_pairs else None)
    retries         = max(0, cfg.getint("BOOT", "CANCEL_VERIFY_RETRIES", fallback=2))
    sleep_ms        = max(100, cfg.getint("BOOT", "CANCEL_VERIFY_SLEEP_MS", fallback=800))

    ulog.info(f"[BOOT] CANCEL_OPEN_ORDERS_ON_START={cancel_on_start} | "
              f"CANCEL_ONLY_CONFIGURED_PAIRS={only_cfg_pairs} | "
              f"CANCEL_DRY_RUN={dry_run} | RETRIES={retries} | SLEEP_MS={sleep_ms}")

    if cancel_on_start:
        try:
            if dry_run:
                ulog.info("DRY-RUN: listaremos ordens abertas, mas não cancelaremos.")
            else:
                # Passo 0: tenta cancelamento "em massa", quando suportado
                await _ccxt_cancel_all_if_supported(ex_hub, targets)

            # Passo 1: cancelamento por ID (via ExchangeHub ou fallback)
            if hasattr(ex_hub, "cancel_all_open_orders"):
                summary = await ex_hub.cancel_all_open_orders(only_pairs=targets, dry_run=dry_run)
            else:
                summary = {}
                for ex_name in ex_hub.enabled_ids:
                    cancelled = 0
                    errors = 0
                    listed = 0

                    async def _fetch_all():
                        try:
                            return await ex_hub.fetch_open_orders(ex_name, global_pair=None)
                        except Exception:
                            orders = []
                            if targets:
                                for p in targets:
                                    try:
                                        orders.extend(await ex_hub.fetch_open_orders(ex_name, global_pair=p))
                                    except Exception:
                                        pass
                            return orders

                    try:
                        opens = await _fetch_all()
                        listed = len(opens)
                        if not dry_run:
                            for o in opens:
                                oid   = str(o.get("id"))
                                gpair = o.get("symbol") or ""   # pode ser local; serve p/ cancelar
                                side  = o.get("side") or None
                                try:
                                    await ex_hub.cancel_order(ex_name, oid, global_pair=gpair, side_hint=side)
                                    cancelled += 1
                                    await asyncio.sleep(0.15)  # alivia rate-limit
                                except Exception:
                                    errors += 1
                    except Exception:
                        errors += 1
                    summary[ex_name] = {"cancelled": cancelled, "errors": errors, "listed": listed}

            # Log por exchange
            for ex_name, ssum in summary.items():
                ulog.info(f"[{ex_name}] abertas listadas={ssum['listed']} | canceladas={ssum['cancelled']} | erros={ssum['errors']}")

            total_cancelled = sum(s['cancelled'] for s in summary.values())

            # Passo 2: verificação com retentativas
            restam = 0
            for i in range(1 + retries):
                await asyncio.sleep(sleep_ms / 1000.0)
                verify = await _post_cancel_verify(ex_hub, targets)
                restam = sum(s['listed'] for s in verify.values())
                if restam == 0 or dry_run:
                    break
                if not dry_run and hasattr(ex_hub, "cancel_all_open_orders"):
                    await ex_hub.cancel_all_open_orders(only_pairs=targets, dry_run=False)

            if dry_run:
                ulog.info("DRY-RUN ativo: apenas listamos ordens abertas (nenhuma foi cancelada).")
            else:
                if restam == 0:
                    # Banner solicitado
                    ulog.info("====================================================")
                    ulog.info("✅ ORDENS CANCELADAS NAS CORRETORAS")
                    ulog.info("✅ SALDO REABASTECIDO PARA INICIAR O BOT")
                    ulog.info("====================================================")
                elif total_cancelled > 0:
                    ulog.warning(f"Cancelamos {total_cancelled} ordens, porém ainda restam {restam} abertas (algumas corretoras podem ter rejeitado/atrasado o cancelamento).")
                else:
                    ulog.warning("Não foi possível cancelar ordens abertas (verifique credenciais/permissões e o log detalhado).")

        except Exception as e:
            ulog.error(f"❌ Falha ao cancelar ordens no boot: {e}")
            log.exception(e)
            ulog.warning("Continuando inicialização sem cancelamento de ordens...")
    else:
        ulog.info("✅ Cancelamento no boot desativado. Para ativar, ajuste [BOOT] no config.")

    # Dica para reduzir "flood" visual no painel
    ulog.info("💡 Dica: para reduzir o redesenho do painel, aumente GLOBAL.PRINT_EVERY_SEC "
              "e/ou defina LOG.CONSOLE_EVENTS=false no config.")

    # -------- FIM CANCELAMENTO DE ORDENS NO BOOT --------

    # Só agora criamos os componentes que podem (re)abrir ordens
    try:
        strategy = StrategySpread(cfg)
        portfolio = Portfolio(cfg, ex_hub)
        risk = RiskManager(cfg)
        state = StateStore(cfg)
        router = OrderRouter(cfg, ex_hub, portfolio, risk, state)
        order_manager = OrderManager(cfg, ex_hub, state, risk)
        monitor = MainMonitor(cfg, ex_hub, strategy, router, order_manager, portfolio, state, risk)
    except Exception as e:
        log.error(f"Falha ao criar componentes: {e}", exc_info=True)
        ulog.error("❌ Falha ao inicializar componentes do bot.")
        await ex_hub.close_all()
        raise

    try:
        ulog.info("✅ Sistema pronto. Iniciando monitoramento...")
        await monitor.run()
    except KeyboardInterrupt:
        log.warning("Interrompido pelo usuário (Ctrl+C). Encerrando...")
        ulog.warning("⏹️  Interrompido pelo usuário. Encerrando...")
    except Exception as e:
        log.error(f"Erro não tratado no loop principal: {e}", exc_info=True)
        ulog.error(f"❌ Erro fatal no bot: {e}")
        raise
    finally:
        ulog.info("🔄 Encerrando conexões...")
        await ex_hub.close_all()
        log.info("Finalizado.")
        ulog.info("✅ Finalizado.")

# ---------------- Entrypoint ----------------

def main():
    """Ponto de entrada principal."""
    args = parse_args()
    
    # Ajusta diretório base para facilitar execução de qualquer lugar
    config_path = Path(args.config).resolve()
    if not config_path.exists():
        print(f"[ERRO] ❌ Arquivo de configuração não encontrado: {config_path}")
        sys.exit(1)
    
    base_dir = config_path.parent
    os.chdir(base_dir)
    
    # Verifica se estamos no diretório correto
    if not (Path.cwd() / "bot.py").exists():
        print(f"[ERRO] ❌ Arquivo bot.py não encontrado no diretório {Path.cwd()}")
        print("       Execute a partir da raiz do projeto ARBIT.")
        sys.exit(1)
    
    try:
        asyncio.run(async_main(str(config_path), db_path_override=args.db_path))
    except KeyboardInterrupt:
        print("\n⏹️  Interrompido pelo usuário.")
        sys.exit(0)
    except Exception as e:
        print(f"[ERRO] ❌ Falha crítica no bot: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
