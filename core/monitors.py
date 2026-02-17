from __future__ import annotations

import asyncio
import statistics
import time
import traceback
from typing import Dict, List, Optional, Tuple, Any
import configparser
import sys
import os
import json
from datetime import datetime

from app.version import APP_VERSION

# >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
# LOG DE QUE ESTE ARQUIVO ESTÁ SENDO CARREGADO
# >>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>
try:
    from utils.logger import get_logger, get_user_logger
except Exception:
    import logging

    def get_logger(name: str):
        return logging.getLogger(name)

    def get_user_logger(name: str):
        return logging.getLogger(name)

log = get_logger("monitor")        # técnico (vai para arquivo detalhado)
ulog = get_user_logger("monitor")  # humano (vai para console)

ulog.info("################################################################")
ulog.info("#### [MONITOR] CARREGANDO ESTE core/monitors.py (shared_state)")
ulog.info("################################################################")

# shared_state em memória para API / frontend
try:
    from api.shared_state import set_snapshot
    ulog.info("[MONITOR] Importado api.shared_state.set_snapshot com sucesso.")
except Exception as e:
    ulog.warning(f"[MONITOR] FALHA ao importar api.shared_state.set_snapshot: {e}")
    set_snapshot = None  # type: ignore


def _resolve_project_root() -> str:
    """
    Resolve a raiz do projeto de forma compatível com:
      - execução normal (python bot.py / run_arbit.py)
      - execução empacotada com PyInstaller (ARBIT_Terminal.exe)
    """
    # Quando empacotado com PyInstaller, sys.frozen é True
    if getattr(sys, "frozen", False):
        # sys.executable -> caminho do .exe (ex.: dist/ARBIT_Terminal/ARBIT_Terminal.exe)
        return os.path.dirname(sys.executable)

    # Execução normal em fonte: volta 2 níveis a partir de core/monitors.py
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---------------- Painel simples in-place ----------------


class _LiveBoard:
    """
    Redesenha o painel no terminal sem criar novas linhas.
    Usa 'cls' no Windows (cmd/PowerShell) e ANSI no *nix.
    Evita flood: não redesenha se o texto não mudou.
    """

    def __init__(self, enabled: bool = True):
        self._enabled = bool(enabled)
        self._last_text = ""

    def _clear_screen(self):
        try:
            if os.name == "nt":
                # Windows: usa o comando nativo para limpar o buffer
                os.system("cls")
            else:
                # *nix: ANSI clear + cursor no topo
                sys.stdout.write("\x1b[2J\x1b[H")
                sys.stdout.flush()
        except Exception:
            # fallback: empurra o conteúdo para cima
            sys.stdout.write("\n" * 120)
            sys.stdout.flush()

    def render(self, text: str):
        if not self._enabled:
            return
        # anti-flood adicional: idempotente
        if text == self._last_text:
            return
        try:
            self._clear_screen()
            sys.stdout.write(text)
            # Garante uma nova linha ao final para não colar no prompt caso algo logue depois
            if not text.endswith("\n"):
                sys.stdout.write("\n")
            sys.stdout.flush()
            self._last_text = text
        except Exception:
            # Fallback rudimentar: imprime muitos \n (evita flood, mas sem in-place)
            print("\n" * 40 + text)
            self._last_text = text

    def finalize(self):
        if not self._enabled:
            return
        # Só adiciona um \n para o próximo print não colar no painel
        try:
            sys.stdout.write("\n")
            sys.stdout.flush()
        except Exception:
            pass


# ---------------- Utils ----------------


def _median(xs: List[float]) -> Optional[float]:
    xs = [float(x) for x in xs if x is not None]
    return statistics.median(xs) if xs else None


class MainMonitor:
    """
    - (Plano B) Cancela ordens no boot, se configurado
    - Imprime saldos relevantes por exchange/par ANTES de negociar
    - Coleta mids por par em todas as exchanges ativas
    - Calça preço de referência (MEDIAN por padrão)
    - Chama o router para (re)posicionar ordens pendentes
      * Se ANCHOR_MODE=LOCAL: o router ancora no book local ± spread para CADA exchange
      * Se ANCHOR_MODE!=LOCAL (ex.: REF): usa os alvos calculados pela strategy
    - Monitora fills e finaliza o ciclo se configurado (ONE_CYCLE_AND_EXIT)
    - Exibe um painel in-place (anti-flood), com ordens por exchange e eventos recentes
    - Gera snapshot em memória (shared_state) para o frontend
    """

    def __init__(
        self,
        cfg: configparser.ConfigParser,
        ex_hub,
        strategy,
        router,
        order_manager,
        portfolio,
        state,
        risk,
        strategy_arbitrage=None,
    ):
        self.cfg = cfg
        self.ex_hub = ex_hub
        self.strategy = strategy
        self.router = router
        self.order_manager = order_manager
        self.portfolio = portfolio
        self.state = state
        self.risk = risk
        self.strategy_arbitrage = strategy_arbitrage

        self.loop_interval_ms = int(self.cfg.get("GLOBAL", "LOOP_INTERVAL_MS", fallback="1200"))
        self.print_every_sec = int(self.cfg.get("GLOBAL", "PRINT_EVERY_SEC", fallback="5"))
        self.use_config_file_pairs = self.cfg.getboolean("GLOBAL", "USE_CONFIG_FILE_PAIRS", fallback=False)

        raw_pairs = self.cfg.get("PAIRS", "LIST", fallback="")
        self.cfg_pairs: List[str] = [p.strip().upper() for p in raw_pairs.split(",") if p.strip()]
        self.pairs: List[str] = list(dict.fromkeys(self.cfg_pairs if self.use_config_file_pairs else []))
        self.global_config: Dict[str, Any] = {}
        self._last_global_updated_at: str = ""

        # Reload operacional orientado por versão de configuração (Sprint 3).
        self.bot_config_cache_ttl_sec = float(
            self.cfg.get("GLOBAL", "BOT_CONFIG_CACHE_TTL_SEC", fallback="0")
        )
        self.bot_configs: Dict[str, Dict[str, Any]] = {}
        self._bot_config_cache_ts: Dict[str, float] = {}
        self._pairs_refresh_ts: float = 0.0
        self.last_seen_config_version: int = 0
        self.last_applied_at: str = ""

        self._reload_configs_if_needed(force=True)

        # router thresholds/flags
        self.min_notional_usdt = float(
            self.cfg.get("ROUTER", "MIN_NOTIONAL_USDT", fallback="5").split(";")[0].strip()
        )
        self.anchor_mode = self.cfg.get("ROUTER", "ANCHOR_MODE", fallback="LOCAL").strip().upper()
        self.one_cycle_exit = self.cfg.get("ROUTER", "ONE_CYCLE_AND_EXIT", fallback="false").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )

        # técnico
        log.info(f"Exchanges habilitadas: {','.join(self.ex_hub.enabled_ids) or '(nenhuma)'}")
        log.info(f"Pares monitorados: {', '.join(self.pairs) or '(nenhum)'}")
        db_pairs_log = [p for p in self.pairs if p not in self.cfg_pairs]
        if db_pairs_log:
            log.info(f"Pares carregados de config_pairs (DB): {', '.join(db_pairs_log)}")
        # humano (mensagens pontuais; o resto vai no painel)
        ulog.info(f"Corretoras ativas: {', '.join(self.ex_hub.enabled_ids) or '(nenhuma)'}")
        ulog.info(f"Pares em operação: {', '.join(self.pairs) or '(nenhum)'}")

        # Painel (agora opcional por config)
        self.panel_enabled = self.cfg.getboolean("GLOBAL", "PANEL_ENABLED", fallback=True)
        self.board = _LiveBoard(enabled=self.panel_enabled)

        # Anti-flood: só redesenha se (a) passou PRINT_EVERY_SEC e (b) algo relevante mudou
        self._next_paint_ts = 0.0
        self.panel_change_only = self.cfg.getboolean("GLOBAL", "PANEL_REDRAW_ON_CHANGE", fallback=True)
        self.panel_force_sec = int(self.cfg.get("GLOBAL", "PANEL_FORCE_REDRAW_SEC", fallback="45"))
        self._last_signature: Optional[str] = None
        self._last_force_ts: float = time.time()

        # Opções visuais extras (reduzem ruído sem tocar no core)
        self.panel_show_mids = self.cfg.getboolean("GLOBAL", "PANEL_SHOW_MIDS", fallback=True)
        self.panel_show_balances = self.cfg.getboolean("GLOBAL", "PANEL_SHOW_BALANCES", fallback=True)
        self.panel_header_show_usdt_brl = self.cfg.getboolean("GLOBAL", "PANEL_HEADER_SHOW_USDT_BRL", fallback=False)

        # Cache de saldos iniciais (para mostrar no painel sem bater API a cada tick)
        self._initial_balances: Dict[str, Dict[str, float]] = {}  # ex -> { "BASE ...": v, "QUOTE ...": v }

        # Buffer de eventos humanos (enviados pelo router via sink)
        self._events_max = int(self.cfg.get("LOG", "EVENTS_MAX", fallback="10"))
        self._events: List[str] = []

        # Conecta o sink de eventos do router ao painel (se suportado)
        try:
            if hasattr(self.router, "set_event_sink"):
                self.router.set_event_sink(self._push_event)
        except Exception:
            pass

        # --------- snapshot em memória + opcional JSON ---------
        project_root = _resolve_project_root()
        snap_cfg = self.cfg.get(
            "GLOBAL",
            "API_SNAPSHOT_PATH",
            fallback="data/api_snapshot.json",
        ).strip()
        if not snap_cfg:
            self.snapshot_path: Optional[str] = None
        elif os.path.isabs(snap_cfg):
            self.snapshot_path = snap_cfg
        else:
            self.snapshot_path = os.path.join(project_root, snap_cfg)

        self._last_snapshot_json: str = ""
        self._last_open_orders_snapshot: List[Dict[str, Any]] = []
        self._marketdata_rows: List[Dict[str, Any]] = []
        self.metrics_service = getattr(self.ex_hub, "metrics", None)

        ulog.info(f"[MONITOR] snapshot_path configurado para: {self.snapshot_path}")

        try:
            self.state.set_runtime_status(
                worker_pid=os.getpid(),
                started_at=time.time(),
                db_path=getattr(self.state, "sqlite_path", ""),
                version=APP_VERSION,
            )
        except Exception as exc:
            log.warning("[runtime_status] falha ao inicializar: %s", exc)

    # ---------------- helpers SPREAD ----------------

    @staticmethod
    def _parse_pct(val: Optional[str], default: float = 0.10) -> float:
        try:
            if val is None:
                return float(default)
            s = str(val).split(";")[0].split("#")[0].strip()
            v = float(s)
            return max(0.0, v)
        except Exception:
            return float(default)

    def _pair_spreads_from_cfg(self, pair: str) -> Tuple[float, float]:
        """
        Resolve spread no DB (pair_spread_config) e cai para config.txt por compatibilidade.
        """
        tenant_id = getattr(self.ex_hub, "tenant_id", "default")
        if hasattr(self.state, "get_pair_spread_config"):
            try:
                spread_cfg = self.state.get_pair_spread_config(tenant_id, pair)
                if spread_cfg and bool(spread_cfg.get("enabled", True)):
                    pct = max(0.0, float(spread_cfg.get("percent") or 0.0)) / 100.0
                    return pct, pct
            except Exception as exc:
                log.warning("[spread_config] falha ao carregar do DB para %s: %s", pair, exc)

        sect = "SPREAD"
        p = pair.strip().upper()

        buy_raw = self.cfg.get(sect, f"{p}_BUY_PCT", fallback=None)
        sell_raw = self.cfg.get(sect, f"{p}_SELL_PCT", fallback=None)
        if buy_raw is not None or sell_raw is not None:
            b = self._parse_pct(buy_raw, 0.10)
            s = self._parse_pct(sell_raw, b)
            return b, s

        single = self.cfg.get(sect, p, fallback=None)
        if single is not None:
            v = self._parse_pct(single, 0.10)
            return v, v

        glob_b = self.cfg.get(sect, "BUY_PCT", fallback=None)
        glob_s = self.cfg.get(sect, "SELL_PCT", fallback=None)
        if glob_b is not None or glob_s is not None:
            b = self._parse_pct(glob_b, 0.10)
            s = self._parse_pct(glob_s, b)
            return b, s

        return 0.10, 0.10

    # ---------------- coleta ----------------

    async def _mid_per_exchange(self, pair: str) -> Dict[str, Optional[float]]:
        tasks = []
        for ex_name in self.ex_hub.enabled_ids:
            tasks.append(self.ex_hub.get_mid_usdt(ex_name, "BUY", pair))
        mids = await asyncio.gather(*tasks, return_exceptions=True)

        out: Dict[str, Optional[float]] = {}
        for (ex_name, mid) in zip(self.ex_hub.enabled_ids, mids):
            if isinstance(mid, Exception):
                log.warning(f"[{pair}] coletor: {ex_name} -> {mid}")
                out[ex_name] = None
            else:
                out[ex_name] = float(mid) if mid is not None else None
        return out

    def _reference_price(self, pair: str, mids: Dict[str, Optional[float]]) -> Optional[float]:
        vals = [m for m in mids.values() if m is not None]
        if not vals:
            return None
        mode = getattr(self.strategy, "ref_mode", "MEDIAN")  # MEDIAN (default) ou VWAP (se implementado)
        if mode == "VWAP":
            # sem dados de volume aqui; usar MEDIAN como fallback
            return _median(vals)
        return _median(vals)

    # ---------------- helpers de saldo/símbolo ----------------

    def _resolve_symbol_for_pair(self, ex_name: str, pair: str) -> Optional[str]:
        """
        Resolve um símbolo local representativo do par na exchange (tenta BUY, senão SELL).
        Usado para descobrir BASE/QUOTE reais (ex.: BTC/BRL na NovaDAX/MB).
        """
        sym = self.ex_hub.resolve_symbol_local(ex_name, "BUY", pair)
        if not sym:
            sym = self.ex_hub.resolve_symbol_local(ex_name, "SELL", pair)
        return sym

    @staticmethod
    def _split_symbol(symbol_local: str) -> Tuple[str, str]:
        if symbol_local and "/" in symbol_local:
            b, q = symbol_local.split("/", 1)
            return b.strip().upper(), q.strip().upper()
        return symbol_local.upper(), "USDT"

    @staticmethod
    def _free_from_balance(bal: Dict, code: str) -> float:
        try:
            if not isinstance(bal, dict):
                return 0.0
            free = bal.get("free", {})
            if isinstance(free, dict) and code in free:
                return float(free[code] or 0.0)
            if code in bal:
                sub = bal.get(code) or {}
                return float((sub.get("free") or 0.0))
        except Exception:
            pass
        return 0.0

    @staticmethod
    def _fmt_updated_at(value: float) -> str:
        if not value:
            return "n/a"
        try:
            return datetime.utcfromtimestamp(float(value)).isoformat() + "Z"
        except Exception:
            return str(value)

    def _refresh_pairs_from_db(self, force: bool = False):
        if not hasattr(self.state, "get_bot_configs"):
            return

        try:
            configs = self.state.get_bot_configs(enabled_only=True) or []
            db_pairs = [str(item.get("pair") or "").strip().upper() for item in configs if item.get("pair")]
            seed_pairs = self.cfg_pairs if self.use_config_file_pairs else []
            self.pairs = list(dict.fromkeys(seed_pairs + db_pairs))
        except Exception as e:
            log.warning(f"[config_reload] falha ao atualizar pares do banco: {e}")

    def _reload_configs_if_needed(self, force: bool = False) -> None:
        if not hasattr(self.state, "get_config_version"):
            if force:
                self._refresh_pairs_from_db(force=True)
            return
        try:
            version_payload = self.state.get_config_version() or {}
            current_version = int(version_payload.get("version") or 0)
            if not force and current_version == self.last_seen_config_version:
                return
            self.bot_configs = {}
            self._bot_config_cache_ts = {}
            self.global_config = self._load_global_config()
            self._refresh_pairs_from_db(force=True)
            self.last_seen_config_version = current_version
            self.last_applied_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
            reason = str(version_payload.get("reason") or "")
            log.info(
                "[CONFIG_APPLIED] version=%s applied_at=%s reason=%s",
                current_version,
                self.last_applied_at,
                reason,
            )
            if hasattr(self.state, "update_runtime_applied_config"):
                self.state.update_runtime_applied_config(
                    config_version=current_version,
                    applied_at=self.last_applied_at,
                    reason=reason,
                )
        except Exception as exc:
            log.warning("[config_reload] falha ao aplicar config por versionamento: %s", exc)

    def _load_global_config(self) -> Dict[str, Any]:
        defaults = {
            "mode": "PAPER",
            "loop_interval_ms": self.loop_interval_ms,
            "kill_switch_enabled": False,
            "max_positions": 1,
            "max_daily_loss": 0.0,
            "updated_at": "",
        }
        if not hasattr(self.state, "get_bot_global_config"):
            return defaults
        try:
            data = self.state.get_bot_global_config() or {}
            cfg = {
                "mode": str(data.get("mode") or defaults["mode"]).upper(),
                "loop_interval_ms": int(data.get("loop_interval_ms") or defaults["loop_interval_ms"]),
                "kill_switch_enabled": bool(data.get("kill_switch_enabled", defaults["kill_switch_enabled"])),
                "max_positions": int(data.get("max_positions") or defaults["max_positions"]),
                "max_daily_loss": float(data.get("max_daily_loss") or defaults["max_daily_loss"]),
                "updated_at": str(data.get("updated_at") or ""),
            }
            return cfg
        except Exception as e:
            log.warning(f"[global_config] falha ao ler config global: {e}")
            return defaults

    def _apply_global_config(self) -> Dict[str, Any]:
        cfg = self._load_global_config()
        self.global_config = cfg

        self.loop_interval_ms = max(100, int(cfg.get("loop_interval_ms") or self.loop_interval_ms))
        if hasattr(self.ex_hub, "mode"):
            self.ex_hub.mode = "PAPER" if str(cfg.get("mode") or "PAPER").upper() == "PAPER" else "LIVE"
        if hasattr(self.risk, "max_open_per_pair_ex"):
            self.risk.max_open_per_pair_ex = max(1, int(cfg.get("max_positions") or 1))
        if hasattr(self.risk, "kill_dd_pct"):
            self.risk.kill_dd_pct = max(0.0, float(cfg.get("max_daily_loss") or 0.0))

        updated_at = str(cfg.get("updated_at") or "")
        if updated_at and updated_at != self._last_global_updated_at:
            log.info(
                "[global_config] updated_at=%s mode=%s loop_interval_ms=%s kill_switch_enabled=%s max_positions=%s max_daily_loss=%.4f",
                updated_at,
                cfg.get("mode"),
                self.loop_interval_ms,
                cfg.get("kill_switch_enabled"),
                cfg.get("max_positions"),
                float(cfg.get("max_daily_loss") or 0.0),
            )
            self._last_global_updated_at = updated_at

        return cfg

    def _load_pair_config(self, pair: str, now: float) -> Dict[str, Any]:
        pair_norm = str(pair or "").strip().upper()
        cached = self.bot_configs.get(pair_norm)
        if cached is not None:
            return cached

        cfg: Dict[str, Any] = {
            "pair": pair_norm,
            "strategy": self.strategy.__class__.__name__,
            "risk_percentage": 0.0,
            "max_daily_loss": 0.0,
            "enabled": True,
            "updated_at": 0.0,
        }

        if hasattr(self.state, "get_bot_configs"):
            try:
                for item in self.state.get_bot_configs(enabled_only=None) or []:
                    if str(item.get("pair") or "").strip().upper() != pair_norm:
                        continue
                    cfg = {
                        "pair": pair_norm,
                        "strategy": str(item.get("strategy") or cfg["strategy"]),
                        "risk_percentage": float(item.get("risk_percentage") or 0.0),
                        "max_daily_loss": float(item.get("max_daily_loss") or 0.0),
                        "enabled": bool(item.get("enabled", True)),
                        "updated_at": float(item.get("updated_at") or 0.0),
                    }
                    break
            except Exception as e:
                log.warning(f"[config_reload] falha ao recarregar config de {pair_norm}: {e}")

        self.bot_configs[pair_norm] = cfg
        self._bot_config_cache_ts[pair_norm] = now
        return cfg

    async def _report_balances(self):
        """
        Imprime o saldo de BASE e QUOTE por exchange/par (símbolo local real),
        ANTES de qualquer tentativa de negociação. Também guarda snapshot para o painel.
        """
        log.info("=== Saldo inicial por exchange/par (BASE | QUOTE) ===")
        self._initial_balances.clear()

        for ex_name in self.ex_hub.enabled_ids:
            try:
                bal = await self.ex_hub.get_balance(ex_name)
            except Exception as e:
                log.warning(f"[{ex_name}] fetch_balance falhou (via hub): {e}")
                ulog.warning(f"Não foi possível ler saldos na {ex_name}.")
                continue

            snap: Dict[str, float] = {}
            for pair in self.pairs:
                sym = self._resolve_symbol_for_pair(ex_name, pair)
                if not sym:
                    log.info(f"[{ex_name}] {pair}: sem símbolo mapeado.")
                    continue
                base, quote = self._split_symbol(sym)
                b_free = self._free_from_balance(bal, base)
                q_free = self._free_from_balance(bal, quote)
                log.info(
                    f"[{ex_name}] {pair} ({sym}) | BASE {base}={b_free:.10f} | "
                    f"QUOTE {quote}={q_free:.10f}"
                )
                snap[base] = snap.get(base, 0.0) + b_free
                snap[quote] = snap.get(quote, 0.0) + q_free

            if snap:
                self._initial_balances[ex_name] = snap

        log.info("=== Fim do relatório de saldos ===")

    # ---------------- eventos (painel) ----------------

    def _push_event(self, msg: str):
        if not isinstance(msg, str):
            msg = str(msg)
        self._events.append(msg)
        if len(self._events) > self._events_max:
            self._events = self._events[-self._events_max:]

    # ---------------- cancelamento no boot (plano B) ----------------
    # (tudo igual ao que você já tinha – mantive a lógica original)
    # --- começo do _boot_cancel_on_start (não alterado) ---

    @staticmethod
    def _fmt_open_order(o: Dict) -> str:
        try:
            oid = str(o.get("id") or o.get("orderId") or "?")
            sym = o.get("symbol") or "?"
            side = str(o.get("side") or "?").upper()
            amt = o.get("amount") if (o.get("amount") is not None) else o.get("origQty")
            filled = o.get("filled")
            price = o.get("price") if (o.get("price") is not None) else o.get("average")
            status = str(o.get("status") or "").upper()
            amt_s = f"{float(amt):g}" if amt is not None else "?"
            fill_s = f"{float(filled):g}" if filled is not None else "?"
            px_s = f"{float(price):g}" if price is not None else "?"
            return f"{sym} | {side:<4s} {amt_s} @ {px_s} (filled={fill_s}) [oid={oid} | {status}]"
        except Exception:
            return str(o)

    async def _boot_cancel_on_start(self):
        """
        Plano B de cancelamento: se [BOOT] exigir, garante cancelamento
        ANTES de começar o monitor, mesmo que o bot.py não tenha feito.
        Só mostra o banner se realmente havia ordens abertas.
        """
        cancel_on = self.cfg.getboolean("BOOT", "CANCEL_OPEN_ORDERS_ON_START", fallback=False)
        if not cancel_on:
            return

        only_cfg = self.cfg.getboolean("BOOT", "CANCEL_ONLY_CONFIGURED_PAIRS", fallback=True)
        dry = self.cfg.getboolean("BOOT", "CANCEL_DRY_RUN", fallback=False)
        list_details = self.cfg.getboolean("BOOT", "CANCEL_LIST_DETAILS", fallback=True)
        list_max = max(1, self.cfg.getint("BOOT", "CANCEL_LIST_MAX", fallback=60))
        retries = max(0, self.cfg.getint("BOOT", "CANCEL_VERIFY_RETRIES", fallback=2))
        sleep_ms = max(100, self.cfg.getint("BOOT", "CANCEL_VERIFY_SLEEP_MS", fallback=800))

        pairs_cfg = [s.strip() for s in self.cfg.get("PAIRS", "LIST", fallback="").split(",") if s.strip()]
        targets = pairs_cfg if only_cfg else None

        pre_listed_total = 0
        pre_details: Dict[str, List[Dict]] = {}
        for ex_name in self.ex_hub.enabled_ids:
            try:
                try:
                    opens = await self.ex_hub.fetch_open_orders(ex_name, global_pair=None)
                except Exception:
                    opens = []
                    if targets:
                        for p in targets:
                            try:
                                opens.extend(await self.ex_hub.fetch_open_orders(ex_name, global_pair=p))
                            except Exception:
                                pass
                pre_listed_total += len(opens or [])
                if list_details and opens:
                    pre_details[ex_name] = opens[:list_max]
            except Exception:
                pass

        if pre_listed_total == 0 and not dry:
            ulog.info("Nenhuma ordem aberta encontrada para cancelar — seguindo.")
            try:
                self._push_event("Boot: nenhuma ordem aberta para cancelar.")
            except Exception:
                pass
            return

        ulog.info("Cancelando ordens pendentes em todas as corretoras antes de iniciar…")
        try:
            self._push_event("Boot: verificação/cancelamento de ordens pendentes…")
        except Exception:
            pass

        if list_details and pre_details:
            ulog.info("Ordens abertas detectadas (amostra):")
            for ex_name, orders in pre_details.items():
                ulog.info(f"  [{ex_name}] {len(orders)} mostradas de até {list_max}:")
                for o in orders:
                    ulog.info("    " + self._fmt_open_order(o))

        if not dry:
            try:
                summary = await self.ex_hub.cancel_all_open_orders(
                    only_pairs=targets,
                    dry_run=False,
                )
                for ex_name, s in (summary or {}).items():
                    ulog.info(
                        f"[{ex_name}] abertas listadas={s.get('listed', 0)} | "
                        f"canceladas={s.get('cancelled', 0)} | erros={s.get('errors', 0)}"
                    )
            except Exception as e:
                log.warning(f"[boot] cancel_all_open_orders (hub) falhou, caindo para fallback: {e}")

        summary: Dict[str, Dict[str, int]] = {}
        for ex_name in self.ex_hub.enabled_ids:
            cancelled = 0
            errors = 0
            listed = 0

            async def _fetch_all():
                try:
                    return await self.ex_hub.fetch_open_orders(ex_name, global_pair=None)
                except Exception:
                    orders = []
                    if targets:
                        for p in targets:
                            try:
                                orders.extend(await self.ex_hub.fetch_open_orders(ex_name, global_pair=p))
                            except Exception:
                                pass
                    return orders

            try:
                opens = await _fetch_all()
                listed = len(opens)
                if listed == 0:
                    summary[ex_name] = {"listed": 0, "cancelled": 0, "errors": 0}
                    continue

                if list_details and dry:
                    ulog.info(f"[{ex_name}] listando {min(listed, list_max)} ordens (DRY-RUN):")
                    for o in opens[:list_max]:
                        ulog.info("  " + self._fmt_open_order(o))

                if not dry:
                    for o in opens:
                        oid = str(o.get("id"))
                        gpair = o.get("symbol") or ""
                        side = o.get("side") or None
                        if list_details:
                            ulog.info(f"[{ex_name}] cancelando: {self._fmt_open_order(o)}")
                        try:
                            await self.ex_hub.cancel_order(ex_name, oid, global_pair=gpair, side_hint=side)
                            cancelled += 1
                            await asyncio.sleep(0.15)
                        except Exception as e:
                            errors += 1
                            log.warning(f"[{ex_name}] falha ao cancelar oid={oid}: {e}")
            except Exception:
                errors += 1

            ulog.info(f"[{ex_name}] abertas listadas={listed} | canceladas={cancelled} | erros={errors}")
            summary[ex_name] = {"listed": listed, "cancelled": cancelled, "errors": errors}

        if dry:
            ulog.info("DRY-RUN ativo: apenas listamos ordens abertas (nenhuma foi cancelada).")
            try:
                self._push_event("Boot: DRY-RUN — apenas listagem, sem cancelamentos.")
            except Exception:
                pass
            return

        restam = 0
        for _i in range(1 + retries):
            await asyncio.sleep(sleep_ms / 1000.0)
            restam = 0
            for ex_name in self.ex_hub.enabled_ids:
                try:
                    try:
                        oo = await self.ex_hub.fetch_open_orders(ex_name, global_pair=None)
                    except Exception:
                        oo = []
                        if targets:
                            for p in targets:
                                try:
                                    oo.extend(await self.ex_hub.fetch_open_orders(ex_name, global_pair=p))
                                except Exception:
                                    pass
                    restam += len(oo or [])
                except Exception:
                    pass
            if restam == 0:
                break

        if restam == 0:
            ulog.info("ORDENS CANCELADAS NAS CORRETORAS — SALDO REABASTECIDO PARA INICIAR O BOT")
            try:
                self._push_event("Boot: ordens canceladas; saldos liberados.")
            except Exception:
                pass
        else:
            total_cancelled = sum(s.get("cancelled", 0) for s in summary.values())
            if total_cancelled > 0:
                ulog.warning(
                    f"Cancelamos {total_cancelled} ordens, porém ainda restam {restam} abertas "
                    f"(a corretora pode ter atrasado/rejeitado parte dos cancelamentos)."
                )
                try:
                    self._push_event(f"Boot: {total_cancelled} canceladas; {restam} ainda abertas.")
                except Exception:
                    pass
            else:
                ulog.warning(
                    "Não foi possível cancelar ordens abertas (verifique credenciais/permissões e o log detalhado)."
                )
                try:
                    self._push_event("Boot: falha ao cancelar ordens (ver logs).")
                except Exception:
                    pass

    # ---------------- assinatura/snapshot para anti-flood (painel) ----------------

    def _panel_signature(self) -> str:
        orders_sig: List[Tuple] = []
        orders = getattr(self.router, "orders", {}) or {}
        for pair in sorted(self.pairs):
            ex_map = orders.get(pair, {}) or {}
            for ex_name in sorted(self.ex_hub.enabled_ids):
                recs = ex_map.get(ex_name, {}) or {}
                for side in ("buy", "sell"):
                    r = recs.get(side) or {}
                    orders_sig.append(
                        (
                            pair,
                            ex_name,
                            side,
                            r.get("symbol") or "",
                            round(float(r.get("qty", 0.0)), 10),
                            round(float(r.get("price_local", 0.0)), 10),
                            bool(r.get("filled", False)),
                            str(r.get("oid") or ""),
                        )
                    )

        events_sig = (len(self._events), self._events[-1] if self._events else "")
        balances_sig = []
        for ex_name in sorted(self._initial_balances.keys()):
            snap = self._initial_balances[ex_name]
            balances_sig.append((ex_name, tuple(sorted((k, round(v, 10)) for k, v in snap.items()))))

        payload = {
            "ex": tuple(sorted(self.ex_hub.enabled_ids)),
            "pairs": tuple(sorted(self.pairs)),
            "anchor": self.anchor_mode,
            "orders": tuple(orders_sig),
            "events": events_sig,
            "balances": tuple(balances_sig),
        }
        try:
            return json.dumps(payload, sort_keys=True, separators=(",", ":"))
        except Exception:
            return str(payload)

    # ---------------- painel ----------------

    def _render_panel(self, ref_map: Dict[str, float], mids_map: Dict[str, Dict[str, Optional[float]]]):
        now_ts = time.time()

        if now_ts < self._next_paint_ts:
            return

        if self.panel_change_only:
            sig = self._panel_signature()
            force_due = (now_ts - self._last_force_ts) >= max(5, self.panel_force_sec)
            if (sig == self._last_signature) and (not force_due):
                return
            self._last_signature = sig
            if force_due:
                self._last_force_ts = now_ts

        self._next_paint_ts = now_ts + max(1, self.print_every_sec)

        now = datetime.now().strftime("%H:%M:%S")
        header = []
        header.append(f"ARBIT — Painel ao vivo  [{now}]")
        exs = ", ".join(self.ex_hub.enabled_ids) or "(nenhuma)"
        if self.panel_header_show_usdt_brl:
            try:
                header.append(
                    f"Modo: {self.anchor_mode} | Exchanges: {exs} | USDT/BRL≈{float(self.ex_hub.usdt_brl):.4f}"
                )
            except Exception:
                header.append(f"Modo: {self.anchor_mode} | Exchanges: {exs}")
        else:
            header.append(f"Modo: {self.anchor_mode} | Exchanges: {exs}")
        header.append(f"Pares: {', '.join(self.pairs) or '(nenhum)'}")
        header.append("")

        body = []

        for pair in self.pairs:
            ref_str = f"{ref_map.get(pair):.6f}" if pair in ref_map else "—"
            b_spread, s_spread = self._pair_spreads_from_cfg(pair)
            body.append(
                f"[{pair}] Ref ≈ {ref_str} USDT | Spread BUY={b_spread*100:.2f}% / SELL={s_spread*100:.2f}%"
            )

            orders_by_ex = (self.router.orders or {}).get(pair, {})

            for ex_name in self.ex_hub.enabled_ids:
                recs = orders_by_ex.get(ex_name, {})
                rec_buy = recs.get("buy")
                rec_sell = recs.get("sell")

                if not rec_buy and not rec_sell:
                    sym = self._resolve_symbol_for_pair(ex_name, pair) or "—"
                    body.append(f"  - {ex_name:<8s} ({sym}): BUY — | SELL —")
                    continue

                if rec_buy:
                    sym_b = rec_buy.get("symbol", "?")
                    qty_b = rec_buy.get("qty", 0.0)
                    pl_b = rec_buy.get("price_local", 0.0)
                    filled_b = rec_buy.get("filled", False)
                    base_b, quote_b = (sym_b.split("/") + ["?"])[:2]
                    px_b = "R$" if quote_b.upper() == "BRL" else "$"
                    buy_str = f"{qty_b:g} {base_b} @ {px_b} {pl_b:g} [{'FILLED' if filled_b else 'ABERTA'}]"
                else:
                    buy_str = "—"

                if rec_sell:
                    sym_s = rec_sell.get("symbol", "?")
                    qty_s = rec_sell.get("qty", 0.0)
                    pl_s = rec_sell.get("price_local", 0.0)
                    filled_s = rec_sell.get("filled", False)
                    base_s, quote_s = (sym_s.split("/") + ["?"])[:2]
                    px_s = "R$" if quote_s.upper() == "BRL" else "$"
                    sell_str = f"{qty_s:g} {base_s} @ {px_s} {pl_s:g} [{'FILLED' if filled_s else 'ABERTA'}]"
                else:
                    sell_str = "—"

                sym_show = (
                    rec_buy.get("symbol")
                    if rec_buy
                    else (rec_sell.get("symbol") if rec_sell else (self._resolve_symbol_for_pair(ex_name, pair) or "?"))
                )
                body.append(f"  - {ex_name:<8s} ({sym_show}): BUY {buy_str} | SELL {sell_str}")

            if self.panel_show_mids:
                mids = mids_map.get(pair, {})
                mids_line = []
                for ex_name in self.ex_hub.enabled_ids:
                    m = mids.get(ex_name)
                    mids_line.append(f"{ex_name}:{m:.4f}" if m is not None else f"{ex_name}:—")
                body.append("    mids: " + " | ".join(mids_line))
            body.append("")

        if self.panel_show_balances and self._initial_balances:
            body.append("Saldos (snapshot inicial):")
            for ex_name, snap in self._initial_balances.items():
                parts = []
                for code in sorted(snap.keys()):
                    val = snap[code]
                    suffix = "R$" if code.upper() == "BRL" else ""
                    parts.append(f"{code}={val:.6f}{suffix}")
                body.append(f"  {ex_name}: " + "  ".join(parts))
            body.append("")

        if self._events:
            body.append("Eventos recentes:")
            for ev in self._events[-self._events_max:]:
                body.append(f"  • {ev}")
            body.append("")

        body.append("Obs.: Este painel é redesenhado; eventos e erros detalhados estão no log de arquivo.")

        text = "\n".join(header + body)
        self.board.render(text)

    # ---------------- ORDENS REAIS PARA SNAPSHOT ----------------

    async def _refresh_open_orders_snapshot(self):
        all_orders: List[Dict[str, Any]] = []

        for ex_name in self.ex_hub.enabled_ids:
            try:
                opens = await self.ex_hub.fetch_open_orders(ex_name, global_pair=None)
            except Exception as e:
                log.warning(f"[snapshot] fetch_open_orders({ex_name}) falhou: {e}")
                continue

            if not opens:
                continue

            for o in opens:
                if not isinstance(o, dict):
                    continue
                rec = dict(o)
                rec["__exchange__"] = ex_name
                all_orders.append(rec)

        self._last_open_orders_snapshot = all_orders

    # ---------------- SNAPSHOT PARA API / SHARED_STATE ----------------

    def _build_api_snapshot(
        self,
        ref_map: Dict[str, float],
        mids_map: Dict[str, Dict[str, Optional[float]]],
    ) -> Dict[str, Any]:
        """
        Monta o snapshot consumido pela API / frontend.

        - balances: usa self._initial_balances
        - mids:      mids por par/corretora
        - orders:    organizado por estado:
            snap["orders"] = {
                "pending": [...],
                "open":    [...],
                "closed":  [...],
            }

          Ordens incluídas:
            * ordens reais das corretoras (self._last_open_orders_snapshot)
            * ordens lógicas do router (slots buy/sell por par+exchange)
        - events: lista de mensagens humanas (Compra aberta, Compra movida, ...)
        """
        snap: Dict[str, Any] = {
            "timestamp": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "mode": self.cfg.get("GLOBAL", "MODE", fallback="PAPER"),
            "pairs": list(self.pairs),
            "exchanges": list(self.ex_hub.enabled_ids),
            "balances": {},
            "mids": {},
            "orders": {
                "pending": [],
                "open": [],
                "closed": [],
            },
            "events": list(self._events[-self._events_max:]),
            "orderbook_status": list(self._marketdata_rows),
            "metrics": self.metrics_service.get_metrics(getattr(self.ex_hub, "tenant_id", "default")) if self.metrics_service else {},
        }

        # ---------- balances ----------
        for ex_name, bmap in self._initial_balances.items():
            ex_bal = {}
            for asset, free_val in bmap.items():
                ex_bal[asset] = {
                    "free": float(free_val),
                    "total": float(free_val),
                }
            snap["balances"][ex_name] = ex_bal

        # ---------- mids ----------
        for pair, mids in (mids_map or {}).items():
            snap["mids"][pair] = {}
            for ex_name, v in mids.items():
                snap["mids"][pair][ex_name] = float(v) if v is not None else None

        # ---------- ordens reais (open/closed das exchanges) ----------
        closed_states = {
            "closed",
            "filled",
            "canceled",
            "cancelled",
            "done",
            "expired",
            "rejected",
        }
        pending_states = {
            "pending",
            "new",
            "created",
        }

        for o in self._last_open_orders_snapshot or []:
            if not isinstance(o, dict):
                continue

            ex_name = o.get("__exchange__", "") or ""
            pair = o.get("pair") or o.get("symbol") or ""
            symbol = o.get("symbol") or pair or ""
            side = str(o.get("side") or "").upper() or "BUY"

            try:
                price = float(o.get("price") or o.get("average") or 0.0)
            except Exception:
                price = 0.0

            try:
                amount = float(
                    o.get("amount") or o.get("origQty") or o.get("qty") or 0.0
                )
            except Exception:
                amount = 0.0

            raw_status = str(o.get("status") or o.get("state") or "open").lower()
            if raw_status in closed_states:
                status = "closed"
            elif raw_status in pending_states:
                status = "pending"
            else:
                status = "open"

            created_at = None
            dt_str = o.get("datetime")
            if isinstance(dt_str, str) and dt_str:
                created_at = dt_str
            else:
                ts = o.get("timestamp")
                if ts is not None:
                    try:
                        ts_f = float(ts)
                        if ts_f > 1e12:
                            ts_f /= 1000.0
                        created_at = datetime.fromtimestamp(ts_f).strftime(
                            "%Y-%m-%d %H:%M:%S"
                        )
                    except Exception:
                        pass
            if not created_at:
                created_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

            client_order_id = str(o.get("clientOrderId") or o.get("client_order_id") or "")
            out = {
                "id": str(o.get("id") or o.get("orderId") or ""),
                "exchange": ex_name,
                "pair": pair,
                "symbol_local": symbol,
                "side": side,
                "price": price,
                "amount": amount,
                "status": status,
                "created_at": created_at,
                "client_order_id": client_order_id,
                "client_order_id_short": (client_order_id[-10:] if client_order_id else ""),
                "dedupe_state": str(o.get("dedupe_state") or ""),
            }

            snap["orders"][status].append(out)

        # ---------- ordens lógicas do router (pendentes / slots) ----------
        try:
            router_orders = getattr(self.router, "orders", {}) or {}
        except Exception:
            router_orders = {}

        if router_orders:
            existing_ids = {
                o.get("id")
                for state_list in snap["orders"].values()
                for o in state_list
                if isinstance(o, dict) and o.get("id")
            }

            for pair in self.pairs:
                ex_map = router_orders.get(pair, {}) or {}
                for ex_name in self.ex_hub.enabled_ids:
                    recs = ex_map.get(ex_name, {}) or {}
                    for side_key in ("buy", "sell"):
                        rec = recs.get(side_key)
                        if not rec:
                            continue

                        oid_raw = rec.get("oid") or rec.get("order_id") or ""
                        oid = str(oid_raw) if oid_raw else ""

                        if oid and oid in existing_ids:
                            continue

                        try:
                            price = float(rec.get("price_local") or rec.get("price") or 0.0)
                        except Exception:
                            price = 0.0

                        try:
                            amount = float(rec.get("qty") or rec.get("amount") or 0.0)
                        except Exception:
                            amount = 0.0

                        sym = rec.get("symbol") or self._resolve_symbol_for_pair(ex_name, pair) or pair
                        created_at = rec.get("created_at")
                        if not created_at:
                            created_at = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

                        filled_flag = bool(rec.get("filled", False))
                        if filled_flag:
                            status = "closed"
                        elif oid:
                            status = "open"
                        else:
                            status = "pending"

                        order_id = oid or f"pending::{ex_name}::{pair}::{side_key}"

                        client_order_id = str(rec.get("client_order_id") or "")
                        out = {
                            "id": order_id,
                            "exchange": ex_name,
                            "pair": pair,
                            "symbol_local": sym,
                            "side": side_key.upper(),
                            "price": price,
                            "amount": amount,
                            "status": status,
                            "created_at": created_at,
                            "client_order_id": client_order_id,
                            "client_order_id_short": str(rec.get("client_order_id_short") or (client_order_id[-10:] if client_order_id else "")),
                            "dedupe_state": str(rec.get("dedupe_state") or ""),
                        }

                        snap["orders"][status].append(out)

        return snap

    def _publish_snapshot(
        self,
        ref_map: Dict[str, float],
        mids_map: Dict[str, Dict[str, Optional[float]]],
    ):
        if set_snapshot is None:
            log.warning("[MONITOR] set_snapshot é None (falha no import) – não há como publicar estado.")
            return

        try:
            snap = self._build_api_snapshot(ref_map, mids_map)
            json_str = json.dumps(snap, ensure_ascii=False, sort_keys=True)

            orders_field = snap.get("orders") or []
            if isinstance(orders_field, list):
                ord_count = len(orders_field)
            elif isinstance(orders_field, dict):
                ord_count = sum(len(v or []) for v in orders_field.values())
            else:
                ord_count = 0

            exs = ", ".join(snap.get("exchanges") or [])
            pairs = ", ".join(snap.get("pairs") or [])

            set_snapshot(snap)
            ulog.info(
                f"[MONITOR] Snapshot publicado em memória: ordens={ord_count} "
                f"| exchanges=[{exs}] | pares=[{pairs}]"
            )

            if self.snapshot_path:
                if json_str != self._last_snapshot_json:
                    self._last_snapshot_json = json_str
                    path = os.path.abspath(self.snapshot_path)
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    tmp = path + ".tmp"
                    with open(tmp, "w", encoding="utf-8") as f:
                        f.write(json_str)
                    os.replace(tmp, path)
                    try:
                        size = os.path.getsize(path)
                        ts = datetime.fromtimestamp(os.path.getmtime(path)).strftime(
                            "%H:%M:%S"
                        )
                        log.info(
                            "[SNAPSHOT] Gravado também em %s (%d bytes às %s)",
                            path,
                            size,
                            ts,
                        )
                    except Exception:
                        pass

        except Exception as e:
            log.warning(f"[MONITOR] falha ao construir/publicar snapshot: {e}")

    # ---------------- loop ----------------

    async def run(self):
        log.info("MainMonitor iniciado.")

        try:
            await self._boot_cancel_on_start()
        except Exception as e:
            log.warning(f"[boot-cancel] falhou: {e}")

        ulog.info("Monitor iniciado. Lendo saldos...")

        try:
            await self._report_balances()
        except Exception as e:
            log.warning(f"[saldo] falhou ao reportar saldos: {e}")
            ulog.warning("Falha ao gerar relatório de saldos.")

        try:
            while True:
                t0 = time.time()
                ref_map: Dict[str, float] = {}
                mids_map: Dict[str, Dict[str, Optional[float]]] = {}

                try:
                    self._reload_configs_if_needed()
                    for ex_name in self.ex_hub.enabled_ids:
                        try:
                            await self.ex_hub.ensure_client_ready(ex_name)
                        except Exception as client_exc:
                            log.warning("[client_ready] exchange=%s error=%s", ex_name, client_exc)
                    global_cfg = self._apply_global_config()
                    if bool(global_cfg.get("kill_switch_enabled")):
                        log.warning("[global_config] kill_switch_enabled=true: ciclo sem envio de ordens.")
                        self._render_panel(ref_map, mids_map)
                    for pair in self.pairs:
                        try:
                            cycle_now = time.time()
                            pair_cfg = self._load_pair_config(pair, cycle_now)

                            cfg_strategy = str(pair_cfg.get("strategy") or self.strategy.__class__.__name__)
                            cfg_enabled = bool(pair_cfg.get("enabled", True))
                            cfg_risk = float(pair_cfg.get("risk_percentage") or 0.0)
                            cfg_max_loss = float(pair_cfg.get("max_daily_loss") or 0.0)
                            cfg_updated_at = float(pair_cfg.get("updated_at") or 0.0)

                            log.info(
                                "[config_reload] ts=%s pair=%s updated_at=%s enabled=%s risk_percentage=%.4f strategy=%s",
                                datetime.utcnow().isoformat() + "Z",
                                pair,
                                self._fmt_updated_at(cfg_updated_at),
                                cfg_enabled,
                                cfg_risk,
                                cfg_strategy,
                            )

                            if not cfg_enabled:
                                log.info(f"[ExecutionEngine] {pair} desabilitado em bot_config. Ignorando.")
                                continue

                            strategy_name = self.strategy.__class__.__name__
                            strategy_lower = cfg_strategy.lower()
                            is_spread = strategy_lower == strategy_name.lower()
                            is_arb = strategy_lower == "strategyarbitragesimple"
                            if not is_spread and not is_arb:
                                log.info(
                                    f"[ExecutionEngine] {pair} configurado para strategy={cfg_strategy}, sem executor registrado. Ignorando par."
                                )
                                continue

                            if bool(global_cfg.get("kill_switch_enabled")):
                                continue

                            log.info(
                                f"[ExecutionEngine] {datetime.utcnow().isoformat()}Z - "
                                f"Symbol: {pair} - Strategy: {cfg_strategy}"
                            )

                            if is_arb:
                                if self.strategy_arbitrage is None:
                                    log.warning(f"[ExecutionEngine] {pair} StrategyArbitrageSimple não inicializada.")
                                    continue
                                arb_cfg = self.state.get_arbitrage_config(getattr(self.ex_hub, "tenant_id", "default"), pair)
                                if not arb_cfg:
                                    log.info(f"[ExecutionEngine] {pair} sem arbitrage_config. Ignorando.")
                                    continue
                                await self.strategy_arbitrage.run_cycle(pair, arb_cfg, global_cfg=global_cfg)
                                continue

                            mids = await self._mid_per_exchange(pair)
                            mids_map[pair] = mids
                            ref = self._reference_price(pair, mids)
                            if ref is not None:
                                ref_map[pair] = float(ref)

                            buy_tgt, sell_tgt = self.strategy.targets_for(
                                pair, float(ref or 0.0)
                            )

                            ref_v = float(ref) if ref is not None else 0.0
                            if self.anchor_mode == "LOCAL":
                                log.info(
                                    f"[{pair}] ref={ref_v:.6f} (informativo) — "
                                    "ANCHOR_MODE=LOCAL: router usará ask/bid "
                                    "locais ± spread configurado."
                                )
                            else:
                                log.info(
                                    f"[{pair}] ref={ref_v:.6f} -> "
                                    f"buy_tgt={buy_tgt:.6f} | sell_tgt={sell_tgt:.6f}"
                                )

                            await self.router.reprice_pair(
                                pair=pair,
                                ref_usdt=float(ref or 0.0),
                                buy_target_usdt=float(buy_tgt),
                                sell_target_usdt=float(sell_tgt),
                                min_notional_usdt=self.min_notional_usdt,
                                risk_percentage=cfg_risk,
                                max_daily_loss=cfg_max_loss,
                            )
                        except Exception as pair_exc:
                            log.error(
                                "[pair_loop] pair=%s error_type=%s message=%s",
                                pair,
                                type(pair_exc).__name__,
                                str(pair_exc),
                                exc_info=True,
                            )
                            continue

                    self._render_panel(ref_map, mids_map)

                except Exception as e:
                    log.error(f"[loop] erro: {e}\n{traceback.format_exc().rstrip()}")
                    ulog.warning("Ocorreu um erro no ciclo. Consultar log detalhado.")

                try:
                    await self.router.poll_fills()
                except Exception:
                    pass

                try:
                    await self._refresh_open_orders_snapshot()
                except Exception as e:
                    log.warning(
                        f"[snapshot] erro ao atualizar lista de ordens abertas: {e}"
                    )

                try:
                    md = getattr(self.ex_hub, "market_data", None)
                    if md is not None:
                        self._marketdata_rows = await md.get_status_rows()
                        if self.metrics_service is not None:
                            self.metrics_service.set_ws_state(getattr(self.ex_hub, "tenant_id", "default"), list(self._marketdata_rows))
                except Exception as e:
                    log.warning(f"[snapshot] erro ao atualizar marketdata status: {e}")

                try:
                    self._publish_snapshot(ref_map, mids_map)
                except Exception as e:
                    log.warning(f"[snapshot] erro ao publicar snapshot: {e}")

                if getattr(self.router, "should_exit", False):
                    log.info(
                        "Encerrando loop: ciclo BUY/SELL concluído (ONE_CYCLE_AND_EXIT)."
                    )
                    ulog.info(
                        "Ciclo concluído: compra e venda executadas. Encerrando."
                    )
                    self.board.finalize()
                    return

                try:
                    self.state.heartbeat_runtime_status(worker_pid=os.getpid())
                except Exception:
                    pass

                elapsed_ms = int((time.time() - t0) * 1000)
                if self.metrics_service is not None:
                    self.metrics_service.record_cycle_latency(getattr(self.ex_hub, "tenant_id", "default"), elapsed_ms)
                sleep_ms = max(0, self.loop_interval_ms - elapsed_ms)
                await asyncio.sleep(sleep_ms / 1000.0 if sleep_ms > 0 else 0)

        except asyncio.CancelledError:
            pass
        finally:
            self.board.finalize()
