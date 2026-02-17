import os
import sys
import json
import logging
import sqlite3
import time
from datetime import datetime
from configparser import ConfigParser, NoOptionError, NoSectionError
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# Se por algum motivo ninguém configurou logging, garante algo no console
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="[API] %(asctime)s %(levelname)s:%(name)s:%(message)s",
    )


def _resolve_project_root() -> str:
    """
    Resolve a raiz do projeto de forma compatível com:
      - execução normal (python server.py / run_arbit.py)
      - execução empacotada com PyInstaller (ARBIT_Terminal.exe)
    """
    if getattr(sys, "frozen", False):
        # PyInstaller: pasta onde está o .exe
        return os.path.dirname(sys.executable)

    # Execução normal: volta 2 níveis de api/handlers.py -> raiz do projeto
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# Estrutura:
# C:\...\1ARBIT\api\handlers.py         ← este arquivo
# C:\...\1ARBIT\config.txt              ← config do bot
#
# PROJECT_ROOT = C:\...\1ARBIT  (ou pasta do .exe quando empacotado)
PROJECT_ROOT = _resolve_project_root()
CONFIG_PATH = os.path.join(PROJECT_ROOT, "config.txt")


def _resolve_sqlite_path(cfg: Optional[ConfigParser] = None) -> str:
    cfg = cfg or _load_config()
    if cfg.has_section("GLOBAL"):
        gsect = cfg["GLOBAL"]
    elif cfg.has_section("GENERAL"):
        gsect = cfg["GENERAL"]
    else:
        gsect = {}
    sqlite_cfg = (gsect.get("SQLITE_PATH", "./data/state.db") or "./data/state.db").strip()
    if not os.path.isabs(sqlite_cfg):
        return os.path.normpath(os.path.join(PROJECT_ROOT, sqlite_cfg))
    return os.path.normpath(sqlite_cfg)


# ================== INTEGRAÇÃO COM ESTADO COMPARTILHADO (API ↔ BOT) ==================

try:
    # Execução como pacote (api.handlers)
    from .shared_state import get_snapshot as _shared_get_snapshot
except Exception:
    try:
        # Execução direta (python handlers.py)
        from shared_state import get_snapshot as _shared_get_snapshot
    except Exception:
        _shared_get_snapshot = None  # sem API acoplada; devolvemos estruturas vazias


def _empty_snapshot() -> Dict[str, Any]:
    """Estrutura vazia padrão, usada quando não há snapshot em memória/arquivo."""
    return {
        "timestamp": None,
        "mode": "UNKNOWN",
        "pairs": [],
        "exchanges": [],
        "balances": {},
        "mids": {},
        "orders": [],
        "events": [],  # lista de strings (eventos humanos do painel)
    }


# ================== CONFIG / LOCALIZAÇÃO DO SNAPSHOT EM ARQUIVO ==================


def _load_config() -> ConfigParser:
    cfg = ConfigParser()
    # Se não achar o arquivo, não explode – só retorna vazio
    if os.path.exists(CONFIG_PATH):
        logger.debug("[API] Lendo config INI em %s", CONFIG_PATH)
        cfg.read(CONFIG_PATH, encoding="utf-8")
    else:
        logger.warning("[API] config.txt não encontrado em %s", CONFIG_PATH)
    return cfg


def _resolve_snapshot_path_from_config() -> Optional[str]:
    """
    Descobre o caminho do arquivo de snapshot a partir do config.txt (GLOBAL.API_SNAPSHOT_PATH),
    caindo no default PROJECT_ROOT/data/api_snapshot.json.
    """
    cfg = _load_config()

    # GLOBAL ou GENERAL (legado)
    if cfg.has_section("GLOBAL"):
        gsect = cfg["GLOBAL"]
    elif cfg.has_section("GENERAL"):
        gsect = cfg["GENERAL"]
    else:
        gsect = {}

    # Caminho configurado (se existir)
    raw_path = gsect.get("API_SNAPSHOT_PATH", "").strip()
    candidates: List[str] = []

    if raw_path:
        # Se for relativo, considera a partir da raiz do projeto
        if not os.path.isabs(raw_path):
            candidates.append(os.path.join(PROJECT_ROOT, raw_path))
        else:
            candidates.append(raw_path)

    # Caminho padrão usado pelo monitor
    candidates.append(os.path.join(PROJECT_ROOT, "data", "api_snapshot.json"))

    # Normaliza e remove duplicados mantendo ordem
    norm_seen = set()
    uniq_candidates: List[str] = []
    for c in candidates:
        c_norm = os.path.normpath(c)
        if c_norm not in norm_seen:
            norm_seen.add(c_norm)
            uniq_candidates.append(c_norm)

    for path in uniq_candidates:
        if os.path.exists(path):
            logger.info("[API] Snapshot JSON encontrado em %s", path)
            return path

    logger.warning(
        "[API] Nenhum arquivo de snapshot encontrado. Tentativas: %s",
        ", ".join(uniq_candidates),
    )
    return None


# ================== SNAPSHOT EM MEMÓRIA + FALLBACK PARA ARQUIVO ==================


def _load_snapshot_from_file() -> Dict[str, Any]:
    """
    Lê o snapshot a partir do arquivo JSON gerado pelo monitor
    (normalmente data/api_snapshot.json).
    """
    path = _resolve_snapshot_path_from_config()
    if not path:
        return _empty_snapshot()

    try:
        with open(path, "r", encoding="utf-8") as f:
            snap = json.load(f)
        if not isinstance(snap, dict):
            logger.warning(
                "[API] Snapshot no arquivo %s não é um dict. Tipo=%s",
                path,
                type(snap),
            )
            return _empty_snapshot()

        logger.info(
            "[API] Snapshot carregado do arquivo %s (chaves=%s)",
            path,
            ", ".join(sorted(snap.keys())),
        )
        return snap
    except Exception as e:
        logger.error(
            "[API] Erro ao ler/parsing snapshot JSON em %s: %s", path, e, exc_info=True
        )
        return _empty_snapshot()


def _normalize_snapshot_structure(snap: Dict[str, Any]) -> Dict[str, Any]:
    """
    Garante que o snapshot tenha sempre as chaves básicas.
    """
    snap.setdefault("timestamp", None)
    snap.setdefault("mode", "UNKNOWN")
    snap.setdefault("pairs", [])
    snap.setdefault("exchanges", [])
    snap.setdefault("balances", {})
    snap.setdefault("mids", {})
    snap.setdefault("orders", [])
    snap.setdefault("events", [])  # sempre garante lista de eventos
    return snap


def _snapshot_has_data(snap: Dict[str, Any]) -> bool:
    """
    Verifica se o snapshot tem algum dado de fato (balances, mids ou orders).
    """
    if not isinstance(snap, dict):
        return False
    if snap.get("balances"):
        return True
    if snap.get("mids"):
        return True
    if snap.get("orders"):
        return True
    return False


def _load_snapshot() -> Dict[str, Any]:
    """
    1) Tenta ler o snapshot em memória via api.shared_state (quando bot+API
       estiverem no MESMO processo).
    2) Se vier vazio ou indisponível, faz fallback para o arquivo JSON
       gerado pelo monitor (data/api_snapshot.json).
    """

    snap: Optional[Dict[str, Any]] = None

    # ---------- TENTA PRIMEIRO EM MEMÓRIA ----------
    if _shared_get_snapshot is not None:
        try:
            snap = _shared_get_snapshot()
        except Exception as e:
            logger.error(
                "[API] Erro ao obter snapshot de shared_state: %s", e, exc_info=True
            )
            snap = None

    if isinstance(snap, dict):
        snap = _normalize_snapshot_structure(snap)
        if _snapshot_has_data(snap):
            try:
                balances = snap.get("balances") or {}
                mids = snap.get("mids") or {}
                orders = snap.get("orders") or []
                logger.info(
                    "[API] Snapshot em memória: exchanges_balances=%d, pares_mids=%d, ordens=%d",
                    len(balances.keys()),
                    len(mids.keys()),
                    len(orders)
                    if isinstance(orders, list)
                    else (
                        sum(len(v) for v in orders.values())
                        if isinstance(orders, dict)
                        else 0
                    ),
                )
            except Exception:
                pass
            return snap
        else:
            logger.info(
                "[API] Snapshot em memória está vazio (mode=%s) – tentando arquivo JSON.",
                snap.get("mode"),
            )
    else:
        if _shared_get_snapshot is None:
            logger.info(
                "[API] shared_state.get_snapshot não disponível – usando apenas arquivo JSON."
            )
        else:
            logger.info(
                "[API] Snapshot em memória ainda não inicializado – tentando arquivo JSON."
            )

    # ---------- FALLBACK PARA ARQUIVO ----------
    snap_file = _load_snapshot_from_file()
    snap_file = _normalize_snapshot_structure(snap_file)

    try:
        balances = snap_file.get("balances") or {}
        mids = snap_file.get("mids") or {}
        orders = snap_file.get("orders") or []
        logger.info(
            "[API] Snapshot do arquivo: exchanges_balances=%d, pares_mids=%d, ordens=%d",
            len(balances.keys()),
            len(mids.keys()),
            len(orders)
            if isinstance(orders, list)
            else (
                sum(len(v) for v in orders.values())
                if isinstance(orders, dict)
                else 0
            ),
        )
    except Exception:
        pass

    return snap_file


# ================== HELPERS SIMPLES ==================


def _safe_float(val, default: float = 0.0) -> float:
    try:
        return float(val)
    except Exception:
        return float(default)


def _safe_int(val, default: int = 0) -> int:
    try:
        return int(str(val).strip())
    except Exception:
        return int(default)


def _safe_bool(val, default: bool = False) -> bool:
    if val is None:
        return bool(default)
    if isinstance(val, bool):
        return val
    s = str(val).strip().lower()
    if s in ("1", "true", "yes", "y", "on"):
        return True
    if s in ("0", "false", "no", "n", "off"):
        return False
    return bool(default)


# ================== FUNÇÃO AUXILIAR PARA FALLBACK DE PARÂMETROS ==================

def _get_param_with_fallback(
    cfg: ConfigParser,
    key: str,
    default: int,
    fallback_sections: Optional[List[str]] = None,
    fallback_keys: Optional[List[str]] = None
) -> int:
    """
    Obtém um parâmetro inteiro com múltiplos fallbacks.
    1. Tenta [GLOBAL][key]
    2. Tenta seções de fallback (ex: [BOOT][key])
    3. Tenta chaves alternativas (ex: HTTP_TIMEOUT ao invés de HTTP_TIMEOUT_SEC)
    4. Usa default
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
                    result = int(value)
                    logger.debug(f"[API] Parâmetro {key}={result} carregado de [{section}][{k}]")
                    return result
            except (KeyError, ValueError, NoOptionError, NoSectionError):
                continue
    
    logger.debug(f"[API] Parâmetro {key} não encontrado, usando default={default}")
    return default


# ================== CONFIG .INI (GLOBAL / STAKE / SPREAD / ETC) ==================


def get_config() -> Dict[str, Any]:
    """
    Lê parâmetros do config para o painel de configurações.

    Mantém os campos antigos (mode/usdt_brl_rate/…) para compatibilidade
    e adiciona grupos organizados (global, boot, router, risk, log, …)
    para o novo painel.
    """
    cfg = _load_config()

    # --- GLOBAL / painel / persistência ---
    if cfg.has_section("GLOBAL"):
        gsect = cfg["GLOBAL"]
    elif cfg.has_section("GENERAL"):  # legado
        gsect = cfg["GENERAL"]
    else:
        gsect = {}

    global_cfg = {
        "mode": gsect.get("MODE", "REAL"),
        "usdt_brl_rate": _safe_float(gsect.get("USDT_BRL_RATE", "5.0"), 5.0),
        "ref_price": gsect.get("REF_PRICE", "MEDIAN"),
        "loop_interval_ms": _safe_int(gsect.get("LOOP_INTERVAL_MS", "1200"), 1200),
        "print_every_sec": _safe_int(gsect.get("PRINT_EVERY_SEC", "5"), 5),
        # painel / anti-flood
        "panel_enabled": _safe_bool(gsect.get("PANEL_ENABLED", "true"), True),
        "panel_redraw_on_change": _safe_bool(
            gsect.get("PANEL_REDRAW_ON_CHANGE", "true"), True
        ),
        "panel_force_redraw_sec": _safe_int(
            gsect.get("PANEL_FORCE_REDRAW_SEC", "45"), 45
        ),
        "panel_header_show_usdt_brl": _safe_bool(
            gsect.get("PANEL_HEADER_SHOW_USDT_BRL", "false"), False
        ),
        "panel_show_mids": _safe_bool(gsect.get("PANEL_SHOW_MIDS", "true"), True),
        "panel_show_balances": _safe_bool(
            gsect.get("PANEL_SHOW_BALANCES", "true"), True
        ),
        # persistência / snapshot (mantidos por compatibilidade)
        "api_snapshot_path": gsect.get(
            "API_SNAPSHOT_PATH", "./data/api_snapshot.json"
        ),
        "sqlite_path": gsect.get("SQLITE_PATH", "./data/state.db"),
        "csv_enable": _safe_bool(gsect.get("CSV_ENABLE", "true"), True),
    }

    # --- BOOT ---
    boot = {}
    if cfg.has_section("BOOT"):
        b = cfg["BOOT"]
        boot = {
            "cancel_open_orders_on_start": _safe_bool(
                b.get("CANCEL_OPEN_ORDERS_ON_START", "false"), False
            ),
            "cancel_only_configured_pairs": _safe_bool(
                b.get("CANCEL_ONLY_CONFIGURED_PAIRS", "true"), True
            ),
            "cancel_dry_run": _safe_bool(b.get("CANCEL_DRY_RUN", "false"), False),
            "cancel_verify_retries": _safe_int(
                b.get("CANCEL_VERIFY_RETRIES", "2"), 2
            ),
            "cancel_verify_sleep_ms": _safe_int(
                b.get("CANCEL_VERIFY_SLEEP_MS", "800"), 800
            ),
            "cancel_list_details": _safe_bool(
                b.get("CANCEL_LIST_DETAILS", "false"), False
            ),
            "cancel_list_max": _safe_int(b.get("CANCEL_LIST_MAX", "60"), 60),
        }

    # CORREÇÃO CRÍTICA: Parâmetros de rede lidos com fallback GLOBAL → BOOT
    # Mantém compatibilidade com configurações antigas e novas
    boot["http_timeout_sec"] = _get_param_with_fallback(
        cfg, "HTTP_TIMEOUT_SEC", 15,
        fallback_sections=["BOOT"],
        fallback_keys=["HTTP_TIMEOUT"]
    )
    boot["max_retries"] = _get_param_with_fallback(
        cfg, "MAX_RETRIES", 3,
        fallback_sections=["BOOT"]
    )
    boot["retry_backoff_ms"] = _get_param_with_fallback(
        cfg, "RETRY_BACKOFF_MS", 400,
        fallback_sections=["BOOT"]
    )

    # Log dos parâmetros carregados
    logger.info(
        f"[API] Parâmetros de rede carregados: "
        f"HTTP_TIMEOUT_SEC={boot['http_timeout_sec']}s, "
        f"MAX_RETRIES={boot['max_retries']}, "
        f"RETRY_BACKOFF_MS={boot['retry_backoff_ms']}ms"
    )

    # --- LOG ---
    log_cfg = {}
    if cfg.has_section("LOG"):
        l = cfg["LOG"]
        log_cfg = {
            "level": l.get("LEVEL", "INFO"),
            "file": l.get("FILE", "./logs/arbit.log"),
            "rotate_mb": _safe_int(l.get("ROTATE_MB", "10"), 10),
            "verbose_skips": _safe_bool(l.get("VERBOSE_SKIPS", "false"), False),
            "console_events": _safe_bool(l.get("CONSOLE_EVENTS", "true"), True),
            "events_max": _safe_int(l.get("EVENTS_MAX", "20"), 20),
            "event_dedup_sec": _safe_int(l.get("EVENT_DEDUP_SEC", "90"), 90),
        }

    # --- RISK ---
    risk = {}
    if cfg.has_section("RISK"):
        r = cfg["RISK"]
        risk = {
            "max_open_orders_per_pair_per_exchange": _safe_int(
                r.get("MAX_OPEN_ORDERS_PER_PAIR_PER_EXCHANGE", "2"), 2
            ),
            "max_gross_exposure_usdt": _safe_float(
                r.get("MAX_GROSS_EXPOSURE_USDT", "500"), 500.0
            ),
            "kill_switch_drawdown_pct": _safe_float(
                r.get("KILL_SWITCH_DRAWDOWN_PCT", "25"), 25.0
            ),
            "cancel_all_on_killswitch": _safe_bool(
                r.get("CANCEL_ALL_ON_KILLSWITCH", "true"), True
            ),
        }

    # --- PAIRS ---
    pairs_cfg = {"list": ""}
    if cfg.has_section("PAIRS"):
        p = cfg["PAIRS"]
        pairs_cfg["list"] = p.get("LIST", "").strip()

    # --- ROUTER ---
    router = {}
    if cfg.has_section("ROUTER"):
        rr = cfg["ROUTER"]
        router = {
            "anchor_mode": rr.get("ANCHOR_MODE", "LOCAL"),
            "sticky_per_side": _safe_bool(rr.get("STICKY_PER_SIDE", "true"), True),
            "min_notional_usdt": _safe_float(rr.get("MIN_NOTIONAL_USDT", "1"), 1.0),
            "track_local_bps": _safe_int(rr.get("TRACK_LOCAL_BPS", "15"), 15),
            "reprice_cooldown_sec": _safe_int(
                rr.get("REPRICE_COOLDOWN_SEC", "5"), 5
            ),
            "place_both_sides_per_exchange": _safe_bool(
                rr.get("PLACE_BOTH_SIDES_PER_EXCHANGE", "true"), True
            ),
            "auto_post_fill_opposite": _safe_bool(
                rr.get("AUTO_POST_FILL_OPPOSITE", "true"), True
            ),
            "post_fill_use_filled_qty": _safe_bool(
                rr.get("POST_FILL_USE_FILLED_QTY", "true"), True
            ),
            "alert_cooldown_sec": _safe_int(
                rr.get("ALERT_COOLDOWN_SEC", "120"), 120
            ),
            "balance_ttl_sec": _safe_int(rr.get("BALANCE_TTL_SEC", "8"), 8),
            "one_cycle_and_exit": _safe_bool(
                rr.get("ONE_CYCLE_AND_EXIT", "false"), False
            ),
        }

    # --- STAKE / SPREAD (raw, por seção) ---
    stake = dict(cfg["STAKE"]) if cfg.has_section("STAKE") else {}
    spread = dict(cfg["SPREAD"]) if cfg.has_section("SPREAD") else {}

    # Retorno com campos antigos (para não quebrar o front atual)
    # + objetos organizados para o novo painel.
    return {
        # legacy / simples
        "mode": global_cfg["mode"],
        "usdt_brl_rate": global_cfg["usdt_brl_rate"],
        "ref_price": global_cfg["ref_price"],
        "loop_interval_ms": global_cfg["loop_interval_ms"],
        "print_every_sec": global_cfg["print_every_sec"],
        "stake": stake,
        "spread": spread,
        # novos grupos organizados
        "global": global_cfg,
        "boot": boot,
        "log": log_cfg,
        "risk": risk,
        "pairs": pairs_cfg,
        "router": router,
    }


def update_config(payload: dict):
    """
    Atualiza parâmetros no config.
    - Mantém suporte aos campos planos usados pelo front atual
      (mode, usdt_brl_rate, ref_price, loop_interval_ms, print_every_sec, stake, spread)
    - Suporta, adicionalmente, objetos agrupados:
        payload["global"], payload["boot"], payload["log"],
        payload["risk"], payload["pairs"], payload["router"]
    """
    cfg = _load_config()

    # --- GLOBAL ---
    if "GLOBAL" not in cfg:
        cfg["GLOBAL"] = {}
    g = cfg["GLOBAL"]

    # campos planos (compatibilidade)
    if "mode" in payload:
        g["MODE"] = str(payload["mode"]).upper()
    if "usdt_brl_rate" in payload:
        g["USDT_BRL_RATE"] = str(payload["usdt_brl_rate"])
    if "ref_price" in payload:
        g["REF_PRICE"] = str(payload["ref_price"]).upper()
    if "loop_interval_ms" in payload:
        g["LOOP_INTERVAL_MS"] = str(int(payload["loop_interval_ms"]))
    if "print_every_sec" in payload:
        g["PRINT_EVERY_SEC"] = str(int(payload["print_every_sec"]))

    # objeto global (novo)
    if "global" in payload and isinstance(payload["global"], dict):
        gg = payload["global"]
        if "mode" in gg:
            g["MODE"] = str(gg["mode"]).upper()
        if "usdt_brl_rate" in gg:
            g["USDT_BRL_RATE"] = str(gg["usdt_brl_rate"])
        if "ref_price" in gg:
            g["REF_PRICE"] = str(gg["ref_price"]).upper()
        if "loop_interval_ms" in gg:
            g["LOOP_INTERVAL_MS"] = str(int(gg["loop_interval_ms"]))
        if "print_every_sec" in gg:
            g["PRINT_EVERY_SEC"] = str(int(gg["print_every_sec"]))

        # painel
        for key_ini, key_json in [
            ("PANEL_ENABLED", "panel_enabled"),
            ("PANEL_REDRAW_ON_CHANGE", "panel_redraw_on_change"),
            ("PANEL_FORCE_REDRAW_SEC", "panel_force_redraw_sec"),
            ("PANEL_HEADER_SHOW_USDT_BRL", "panel_header_show_usdt_brl"),
            ("PANEL_SHOW_MIDS", "panel_show_mids"),
            ("PANEL_SHOW_BALANCES", "panel_show_balances"),
        ]:
            if key_json in gg:
                g[key_ini] = "true" if _safe_bool(gg[key_json]) else "false"

        # persistência / snapshot
        if "api_snapshot_path" in gg:
            g["API_SNAPSHOT_PATH"] = str(gg["api_snapshot_path"])
        if "sqlite_path" in gg:
            g["SQLITE_PATH"] = str(gg["sqlite_path"])
        if "csv_enable" in gg:
            g["CSV_ENABLE"] = "true" if _safe_bool(gg["csv_enable"]) else "false"

    # --- STAKE / SPREAD ---
    if "stake" in payload and isinstance(payload["stake"], dict):
        cfg["STAKE"] = {}
        for k, v in payload["stake"].items():
            cfg["STAKE"][k] = str(v)

    if "spread" in payload and isinstance(payload["spread"], dict):
        cfg["SPREAD"] = {}
        for k, v in payload["spread"].items():
            cfg["SPREAD"][k] = str(v)

    # --- BOOT ---
    if "boot" in payload and isinstance(payload["boot"], dict):
        if "BOOT" not in cfg:
            cfg["BOOT"] = {}
        b = cfg["BOOT"]
        bb = payload["boot"]

        def _set_bool(key_ini, key_json):
            if key_json in bb:
                b[key_ini] = "true" if _safe_bool(bb[key_json]) else "false"

        def _set_any(key_ini, key_json):
            if key_json in bb:
                b[key_ini] = str(bb[key_json])

        _set_bool("CANCEL_OPEN_ORDERS_ON_START", "cancel_open_orders_on_start")
        _set_bool("CANCEL_ONLY_CONFIGURED_PAIRS", "cancel_only_configured_pairs")
        _set_bool("CANCEL_DRY_RUN", "cancel_dry_run")
        _set_any("CANCEL_VERIFY_RETRIES", "cancel_verify_retries")
        _set_any("CANCEL_VERIFY_SLEEP_MS", "cancel_verify_sleep_ms")
        _set_bool("CANCEL_LIST_DETAILS", "cancel_list_details")
        _set_any("CANCEL_LIST_MAX", "cancel_list_max")

        # CORREÇÃO CRÍTICA: Parâmetros de rede vão para GLOBAL, não BOOT
        # Isso resolve a inconsistência BOOT vs GLOBAL
        if "http_timeout_sec" in bb:
            cfg["GLOBAL"]["HTTP_TIMEOUT_SEC"] = str(bb["http_timeout_sec"])
        if "max_retries" in bb:
            cfg["GLOBAL"]["MAX_RETRIES"] = str(bb["max_retries"])
        if "retry_backoff_ms" in bb:
            cfg["GLOBAL"]["RETRY_BACKOFF_MS"] = str(bb["retry_backoff_ms"])

    # --- LOG ---
    if "log" in payload and isinstance(payload["log"], dict):
        if "LOG" not in cfg:
            cfg["LOG"] = {}
        l = cfg["LOG"]
        ll = payload["log"]

        for key_ini, key_json in [
            ("LEVEL", "level"),
            ("FILE", "file"),
            ("ROTATE_MB", "rotate_mb"),
            ("VERBOSE_SKIPS", "verbose_skips"),
            ("CONSOLE_EVENTS", "console_events"),
            ("EVENTS_MAX", "events_max"),
            ("EVENT_DEDUP_SEC", "event_dedup_sec"),
        ]:
            if key_json in ll:
                if key_ini in ("VERBOSE_SKIPS", "CONSOLE_EVENTS"):
                    l[key_ini] = "true" if _safe_bool(ll[key_json]) else "false"
                else:
                    l[key_ini] = str(ll[key_json])

    # --- RISK ---
    if "risk" in payload and isinstance(payload["risk"], dict):
        if "RISK" not in cfg:
            cfg["RISK"] = {}
        r = cfg["RISK"]
        rr = payload["risk"]

        mapping = {
            "MAX_OPEN_ORDERS_PER_PAIR_PER_EXCHANGE": "max_open_orders_per_pair_per_exchange",
            "MAX_GROSS_EXPOSURE_USDT": "max_gross_exposure_usdt",
            "KILL_SWITCH_DRAWDOWN_PCT": "kill_switch_drawdown_pct",
            "CANCEL_ALL_ON_KILLSWITCH": "cancel_all_on_killswitch",
        }
        for ini_key, json_key in mapping.items():
            if json_key in rr:
                if ini_key == "CANCEL_ALL_ON_KILLSWITCH":
                    r[ini_key] = "true" if _safe_bool(rr[json_key]) else "false"
                else:
                    r[ini_key] = str(rr[json_key])

    # --- PAIRS ---
    if "pairs" in payload and isinstance(payload["pairs"], dict):
        if "PAIRS" not in cfg:
            cfg["PAIRS"] = {}
        p = cfg["PAIRS"]
        if "list" in payload["pairs"]:
            p["LIST"] = str(payload["pairs"]["list"])

    # --- ROUTER ---
    if "router" in payload and isinstance(payload["router"], dict):
        if "ROUTER" not in cfg:
            cfg["ROUTER"] = {}
        r = cfg["ROUTER"]
        rr = payload["router"]

        def _set_r(key_ini, key_json, is_bool: bool = False):
            if key_json in rr:
                if is_bool:
                    r[key_ini] = "true" if _safe_bool(rr[key_json]) else "false"
                else:
                    r[key_ini] = str(rr[key_json])

        _set_r("ANCHOR_MODE", "anchor_mode")
        _set_r("STICKY_PER_SIDE", "sticky_per_side", True)
        _set_r("MIN_NOTIONAL_USDT", "min_notional_usdt")
        _set_r("TRACK_LOCAL_BPS", "track_local_bps")
        _set_r("REPRICE_COOLDOWN_SEC", "reprice_cooldown_sec")
        _set_r("PLACE_BOTH_SIDES_PER_EXCHANGE", "place_both_sides_per_exchange", True)
        _set_r("AUTO_POST_FILL_OPPOSITE", "auto_post_fill_opposite", True)
        _set_r("POST_FILL_USE_FILLED_QTY", "post_fill_use_filled_qty", True)
        _set_r("ALERT_COOLDOWN_SEC", "alert_cooldown_sec")
        _set_r("BALANCE_TTL_SEC", "balance_ttl_sec")
        _set_r("ONE_CYCLE_AND_EXIT", "one_cycle_and_exit", True)

    # Grava INI
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        cfg.write(f)

    logger.info("[API] Configuração atualizada e gravada em %s", CONFIG_PATH)
    return True, "Configuração atualizada com sucesso."


# ================== SNAPSHOT DO BOT (em memória/arquivo) ==================




def get_bot_configs() -> Dict[str, Any]:
    """Retorna a lista de bot_config por par (tabela config_pairs)."""
    cfg = _load_config()
    db_path = _resolve_sqlite_path(cfg)
    if not os.path.exists(db_path):
        return {"items": [], "sqlite_path": db_path}

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT
                symbol,
                COALESCE(strategy, 'StrategySpread') AS strategy,
                COALESCE(risk_percentage, 0) AS risk_percentage,
                COALESCE(max_daily_loss, 0) AS max_daily_loss,
                COALESCE(enabled, 1) AS enabled,
                COALESCE(updated_at, 0) AS updated_at
            FROM config_pairs
            ORDER BY symbol
            """
        ).fetchall()
        items = []
        for row in rows:
            items.append(
                {
                    "pair": str(row["symbol"] or ""),
                    "strategy": str(row["strategy"] or "StrategySpread"),
                    "risk_percentage": float(row["risk_percentage"] or 0.0),
                    "max_daily_loss": float(row["max_daily_loss"] or 0.0),
                    "enabled": bool(row["enabled"]),
                    "updated_at": float(row["updated_at"] or 0.0),
                }
            )
        return {"items": items, "sqlite_path": db_path}
    finally:
        conn.close()


def upsert_bot_config(payload: Dict[str, Any]):
    """Cria/atualiza bot_config por par em config_pairs."""
    pair = str(payload.get("pair") or payload.get("symbol") or "").strip().upper().replace("-", "/")
    if not pair:
        return False, "Campo 'pair' é obrigatório."

    strategy = str(payload.get("strategy") or "StrategySpread").strip() or "StrategySpread"
    risk_percentage = _safe_float(payload.get("risk_percentage"), 0.0)
    max_daily_loss = _safe_float(payload.get("max_daily_loss"), 0.0)
    enabled = _safe_bool(payload.get("enabled"), True)
    updated_at = time.time()

    cfg = _load_config()
    db_path = _resolve_sqlite_path(cfg)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS config_pairs (
                symbol TEXT PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 1,
                strategy TEXT,
                risk_percentage REAL,
                max_daily_loss REAL,
                updated_at REAL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO config_pairs(symbol, enabled, strategy, risk_percentage, max_daily_loss, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                enabled=excluded.enabled,
                strategy=excluded.strategy,
                risk_percentage=excluded.risk_percentage,
                max_daily_loss=excluded.max_daily_loss,
                updated_at=excluded.updated_at
            """,
            (
                pair,
                1 if enabled else 0,
                strategy,
                float(risk_percentage),
                float(max_daily_loss),
                float(updated_at),
            ),
        )
        conn.commit()
    except Exception as e:
        return False, f"Falha ao salvar bot_config: {e}"
    finally:
        conn.close()

    return True, f"bot_config salvo para {pair}."

def debug_snapshot() -> Dict[str, Any]:
    """
    Endpoint de debug para inspecionar rapidamente o snapshot em memória/arquivo.
    """
    snap = _load_snapshot()

    balances = snap.get("balances") or {}
    mids = snap.get("mids") or {}
    orders = snap.get("orders") or []
    events = snap.get("events") or []

    if isinstance(orders, dict):
        total_orders = sum(len(v or []) for v in orders.values())
    elif isinstance(orders, list):
        total_orders = len(orders)
    else:
        total_orders = 0

    if not isinstance(events, list):
        events_list: List[str] = [str(events)]
    else:
        events_list = [str(e) for e in events]

    return {
        "ok": True,
        "timestamp": snap.get("timestamp"),
        "mode": snap.get("mode"),
        "pairs": snap.get("pairs") or [],
        "exchanges": snap.get("exchanges") or [],
        "balances_exchanges": sorted(list(balances.keys())),
        "mids_pairs": sorted(list(mids.keys())),
        "orders_total": total_orders,
        "events_total": len(events_list),
        "raw_preview": {
            "balances": balances,
            "mids": mids,
            "orders_sample": orders[:5] if isinstance(orders, list) else orders,
            "events_sample": events_list[-5:],
        },
    }


# ================== ENDPOINTS: balances / orders / mids / events ==================


def get_balances() -> Dict[str, Any]:
    """
    Lê os saldos do snapshot do bot (em memória/arquivo).
    Estrutura retornada pelo endpoint:
    {
        "mercadobitcoin": {
            "BRL": {"free": 2500.0, "total": 2500.0},
            ...
        },
        "novadax": { ... },
        ...
    }
    """
    snap = _load_snapshot()
    balances = snap.get("balances", {}) or {}

    logger.info(
        "[API] get_balances: exchanges=%s",
        ", ".join(sorted(balances.keys())) or "(nenhuma)",
    )

    return balances


def get_orders(state: str) -> Dict[str, List[Dict[str, Any]]]:
    """
    Retorna ordens a partir do snapshot em memória/arquivo.

    Suporta múltiplos formatos de snapshot:

    1) "orders": { "pending": [...], "open": [...], "closed": [...] }
       (formato atual do seu api_snapshot.json)
    2) "orders": [ { "state": "pending", ... }, ... ]
    3) "orders": [ { "status": "open"/"filled"/"cancelled", ... }, ... ]  (legacy)

    Em todos os casos, o retorno é:
    {
        "orders": [ { "id": "...", "exchange": "...", ... }, ... ]
    }
    """
    snap = _load_snapshot()
    raw = snap.get("orders", []) or []

    state = (state or "").lower()
    orders_list: List[Dict[str, Any]] = []

    # -------- formato 1: dict por estado (igual ao que apareceu no debug) --------
    if isinstance(raw, dict):
        # Ex.: raw = { "pending": [...], "open": [...], "closed": [...] }
        pending_list = raw.get("pending") or []
        open_list = raw.get("open") or []
        closed_list = raw.get("closed") or []

        # No SEU domínio:
        #  - tudo que está "no book" é ORDEM PENDENTE
        #  - ou seja: pending + open do snapshot vão para o estado "pending" da API
        if state == "pending":
            orders_list = []
            if isinstance(pending_list, list):
                orders_list.extend(pending_list)
            if isinstance(open_list, list):
                orders_list.extend(open_list)

        elif state == "open":
            # Ainda não temos no snapshot as "ordens executadas" (posições abertas).
            # Mantemos vazio até ligarmos isso no portfolio/order_manager/state.
            orders_list = []

        elif state == "closed":
            if isinstance(closed_list, list):
                orders_list = closed_list

        else:
            # state desconhecido -> concatena tudo
            tmp: List[Dict[str, Any]] = []
            for v in raw.values():
                if isinstance(v, list):
                    tmp.extend(v)
            orders_list = tmp

    # -------- formato 2 / 3: lista única --------
    elif isinstance(raw, list):
        # Se existir campo "state", usa diretamente
        if any(isinstance(o, dict) and "state" in o for o in raw):
            orders_list = [
                o
                for o in raw
                if isinstance(o, dict)
                and str(o.get("state", "")).lower() == state
            ]
        else:
            # Fallback por STATUS (lógica antiga)
            def norm_status(o: Dict[str, Any]) -> str:
                return str(o.get("status", "")).lower()

            if state == "pending":
                # PENDENTE = ordem viva no book (ou recém criada)
                pending_status = {
                    "pending",
                    "new",
                    "created",
                    "open",
                    "partially_filled",
                    "live",
                }
                orders_list = [o for o in raw if norm_status(o) in pending_status]
            elif state == "open":
                # "open" aqui ficaria reservado para quando você passar a registrar
                # ordens executadas/posições no snapshot.
                orders_list = []
            elif state == "closed":
                closed_status = {
                    "closed",
                    "filled",
                    "canceled",
                    "cancelled",
                    "done",
                    "expired",
                    "rejected",
                }
                orders_list = [o for o in raw if norm_status(o) in closed_status]
            else:
                # fallback: devolve tudo
                orders_list = list(raw)

    else:
        # formato inesperado – devolve vazio
        orders_list = []

    logger.info(
        "[API] get_orders(state=%s): total_snapshot=%d, retornadas=%d",
        state or "(vazio)",
        len(raw)
        if isinstance(raw, list)
        else (sum(len(v) for v in raw.values()) if isinstance(raw, dict) else 0),
        len(orders_list),
    )

    return {"orders": orders_list}



def get_mids(pair: str) -> Dict[str, Any]:
    """
    Retorna mids por corretora para um par, a partir do snapshot em memória/arquivo.

    Suporta múltiplos formatos de snapshot:

    1) "mids": { "SOL-USDT": { "gate": 123.4, "mexc": 123.5 }, "BTC-USDT": {...} }
    2) "mids": { "gate": 123.4, "mexc": 123.5 }   # já é o dict por corretora

    O retorno é sempre:
    {
        "pair": "SOL-USDT",
        "mids": {
            "mercadobitcoin": 134416.2,
            ...
        }
    }
    """
    snap = _load_snapshot()
    pair_norm = (pair or "").upper()
    mids_root = snap.get("mids", {}) or {}

    mids_pair: Dict[str, Any] = {}

    # Caso 1: dict por par (valores também são dicts)
    if isinstance(mids_root, dict) and any(
        isinstance(v, dict) for v in mids_root.values()
    ):
        # primeiro tenta chave exatamente igual
        mids_pair = mids_root.get(pair_norm, {}) or {}

        # se não achar, normaliza SOL/USDT x SOL-USDT
        if not mids_pair:
            for k, v in mids_root.items():
                if not isinstance(v, dict):
                    continue
                if k.replace("/", "-").upper() == pair_norm.replace("/", "-").upper():
                    mids_pair = v
                    break
    else:
        # Caso 2: já veio como { exchange: price }
        mids_pair = mids_root

    logger.info(
        "[API] get_mids(%s): exchanges=%s",
        pair_norm or "(vazio)",
        ", ".join(sorted(mids_pair.keys())) or "(nenhuma)",
    )

    return {
        "pair": pair_norm,
        "mids": mids_pair or {},
    }


def get_events(limit: int = 50) -> Dict[str, Any]:
    """
    Retorna a fila de eventos humanos (ex.: 'Compra aberta...', 'Compra movida...')
    que o monitor envia para o painel.

    Espera que o snapshot tenha a chave 'events' como lista de strings,
    mas é tolerante com outros formatos.
    """
    snap = _load_snapshot()
    raw_events = snap.get("events") or []

    if not isinstance(raw_events, list):
        events_list: List[str] = [str(raw_events)]
    else:
        events_list = [str(e) for e in raw_events]

    if limit and limit > 0:
        events_out = events_list[-limit:]
    else:
        events_out = events_list

    logger.info(
        "[API] get_events(limit=%d): total_snapshot=%d, retornadas=%d",
        limit,
        len(events_list),
        len(events_out),
    )

    return {"events": events_out}
