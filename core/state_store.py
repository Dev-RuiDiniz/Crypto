# core/state_store.py
# Persistência simples:
# - SQLite (./data/state.db) com tabelas de orders, fills e event_log
# - CSV opcional (orders.csv, fills.csv) se CSV_ENABLE=true no config

from __future__ import annotations

import sqlite3
import json
import time
import os
import csv
from typing import Optional, Dict, Any, List

import configparser

try:
    from utils.logger import get_logger
except Exception:
    import logging
    def get_logger(name: str): return logging.getLogger(name)

log = get_logger("state_store")


class StateStore:
    def __init__(self, cfg: configparser.ConfigParser):
        self.cfg = cfg
        self.sqlite_path = os.path.abspath(self.cfg.get("GLOBAL", "SQLITE_PATH", fallback="./data/state.db"))
        self.csv_enable = self.cfg.getboolean("GLOBAL", "CSV_ENABLE", fallback=True)

        # Garante pasta
        os.makedirs(os.path.dirname(os.path.abspath(self.sqlite_path)), exist_ok=True)

        # Conexão principal
        self._conn = sqlite3.connect(self.sqlite_path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._conn.row_factory = sqlite3.Row
        self._init_db()

        # CSV paths
        base_dir = os.path.dirname(self.sqlite_path)
        self._orders_csv = os.path.join(base_dir, "orders.csv")
        self._fills_csv = os.path.join(base_dir, "fills.csv")
        if self.csv_enable:
            self._ensure_csv_headers()

    # ------------------------------------------------------------------
    # INIT / SCHEMA

    def _init_db(self):
        cur = self._conn.cursor()
        cur.execute(
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
        # Migração mínima para bancos existentes: adiciona colunas de bot_config se faltarem.
        existing_cols = {
            str(r[1]).lower()
            for r in cur.execute("PRAGMA table_info(config_pairs)").fetchall()
        }
        if "strategy" not in existing_cols:
            cur.execute("ALTER TABLE config_pairs ADD COLUMN strategy TEXT")
        if "risk_percentage" not in existing_cols:
            cur.execute("ALTER TABLE config_pairs ADD COLUMN risk_percentage REAL")
        if "max_daily_loss" not in existing_cols:
            cur.execute("ALTER TABLE config_pairs ADD COLUMN max_daily_loss REAL")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS orders (
                id TEXT PRIMARY KEY,
                ts REAL,
                ex_name TEXT,
                pair TEXT,
                side TEXT,
                symbol_local TEXT,
                price_local REAL,
                amount REAL,
                status TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS fills (
                id TEXT,
                ts REAL,
                ex_name TEXT,
                pair TEXT,
                side TEXT,
                symbol_local TEXT,
                price_local REAL,
                price_usdt REAL,
                amount REAL,
                fee REAL,
                info TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS event_log (
                ts REAL,
                type TEXT,
                payload TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_orders (
                id TEXT PRIMARY KEY,
                ts REAL,
                pair TEXT,
                strategy TEXT,
                side TEXT,
                risk_percentage REAL,
                qty REAL,
                notional_usdt REAL,
                cycle_id TEXT,
                payload TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS runtime_status (
                worker_pid INTEGER,
                started_at REAL,
                last_heartbeat_at REAL,
                db_path TEXT,
                version TEXT
            )
            """
        )
        self._conn.commit()

    @staticmethod
    def _normalize_symbol(symbol: str) -> str:
        s = (symbol or "").strip().upper().replace("-", "/")
        if not s:
            return ""
        if "/" in s:
            base, quote = s.split("/", 1)
            return f"{base.strip()}/{quote.strip()}"
        for quote in ("USDT", "USDC", "BRL", "BTC", "ETH"):
            if s.endswith(quote) and len(s) > len(quote):
                base = s[: -len(quote)]
                if base:
                    return f"{base}/{quote}"
        return s

    def get_enabled_pairs(self) -> List[str]:
        """
        Lista pares habilitados da tabela config_pairs para uso no scheduler/monitor.
        """
        try:
            rows = self._conn.execute(
                "SELECT symbol FROM config_pairs WHERE COALESCE(enabled, 1) = 1 ORDER BY symbol"
            ).fetchall()
        except Exception as e:
            log.warning(f"[config_pairs] leitura falhou: {e}")
            return []

        out: List[str] = []
        for row in rows:
            normalized = self._normalize_symbol(str(row["symbol"] if isinstance(row, sqlite3.Row) else row[0]))
            if normalized:
                out.append(normalized)
        return out

    def get_bot_configs(self, enabled_only: Optional[bool] = None) -> List[Dict[str, Any]]:
        """
        Retorna bot_config no formato esperado pelo executor.

        enabled_only:
          - True: somente habilitados
          - False: somente desabilitados
          - None: todos
        """
        where_clause = ""
        if enabled_only is True:
            where_clause = "WHERE COALESCE(enabled, 1) = 1"
        elif enabled_only is False:
            where_clause = "WHERE COALESCE(enabled, 1) = 0"

        try:
            rows = self._conn.execute(
                f"""
                SELECT
                    symbol,
                    COALESCE(strategy, 'StrategySpread') AS strategy,
                    COALESCE(risk_percentage, 0) AS risk_percentage,
                    COALESCE(max_daily_loss, 0) AS max_daily_loss,
                    COALESCE(enabled, 1) AS enabled,
                    updated_at
                FROM config_pairs
                {where_clause}
                ORDER BY symbol
                """
            ).fetchall()
        except Exception as e:
            log.warning(f"[config_pairs] leitura de bot_config falhou: {e}")
            return []

        out: List[Dict[str, Any]] = []
        for row in rows:
            raw_pair = str(row["symbol"] if isinstance(row, sqlite3.Row) else row[0])
            pair = self._normalize_symbol(raw_pair)
            if not pair:
                continue
            out.append(
                {
                    "pair": pair,
                    "strategy": str((row["strategy"] if isinstance(row, sqlite3.Row) else row[1]) or "StrategySpread"),
                    "risk_percentage": float((row["risk_percentage"] if isinstance(row, sqlite3.Row) else row[2]) or 0.0),
                    "max_daily_loss": float((row["max_daily_loss"] if isinstance(row, sqlite3.Row) else row[3]) or 0.0),
                    "enabled": bool((row["enabled"] if isinstance(row, sqlite3.Row) else row[4]) or 0),
                    "updated_at": float((row["updated_at"] if isinstance(row, sqlite3.Row) else row[5]) or 0.0),
                }
            )
        return out

    def get_enabled_bot_configs(self) -> List[Dict[str, Any]]:
        """
        Retorna bot_config habilitados no formato esperado pelo executor.
        """
        return self.get_bot_configs(enabled_only=True)

    def _ensure_csv_headers(self):
        if not os.path.exists(self._orders_csv):
            try:
                with open(self._orders_csv, "w", newline="", encoding="utf-8") as f:
                    w = csv.writer(f)
                    w.writerow(["ts","id","ex_name","pair","side","symbol_local","price_local","amount","status"])
            except Exception as e:
                log.warning(f"[orders.csv][header] falha: {e}")

        if not os.path.exists(self._fills_csv):
            try:
                with open(self._fills_csv, "w", newline="", encoding="utf-8") as f:
                    w = csv.writer(f)
                    w.writerow(["ts","id","ex_name","pair","side","symbol_local",
                                "price_local","price_usdt","amount","fee","info"])
            except Exception as e:
                log.warning(f"[fills.csv][header] falha: {e}")

    # ------------------------------------------------------------------
    # API pública — gravação

    def set_runtime_status(self, worker_pid: int, started_at: float, db_path: str, version: str) -> None:
        try:
            self._conn.execute("DELETE FROM runtime_status")
            self._conn.execute(
                """
                INSERT INTO runtime_status(worker_pid, started_at, last_heartbeat_at, db_path, version)
                VALUES (?, ?, ?, ?, ?)
                """,
                (int(worker_pid), float(started_at), float(time.time()), str(db_path), str(version)),
            )
            self._conn.commit()
        except Exception as e:
            log.warning(f"[runtime_status] set falha: {e}")

    def heartbeat_runtime_status(self, worker_pid: int) -> None:
        try:
            self._conn.execute(
                """
                UPDATE runtime_status
                SET last_heartbeat_at = ?, worker_pid = ?
                """,
                (float(time.time()), int(worker_pid)),
            )
            self._conn.commit()
        except Exception as e:
            log.warning(f"[runtime_status] heartbeat falha: {e}")

    def log_event(self, event_type: str, payload: Dict[str, Any]):
        ts = time.time()
        try:
            self._conn.execute(
                "INSERT INTO event_log (ts, type, payload) VALUES (?, ?, ?)",
                (ts, event_type, json.dumps(payload, ensure_ascii=False)),
            )
            self._conn.commit()
        except Exception as e:
            log.warning(f"[event_log] falha: {e}")

    def record_order_create(self, live_order) -> None:
        """
        Espera um objeto compatível com LiveOrder (tem atributos: order_id, ...).
        """
        ts = time.time()
        try:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO orders
                (id, ts, ex_name, pair, side, symbol_local, price_local, amount, status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(live_order.order_id),
                    ts,
                    live_order.ex_name,
                    live_order.pair,
                    live_order.side,
                    live_order.symbol_local,
                    float(live_order.price_local),
                    float(live_order.amount),
                    live_order.status,
                ),
            )
            self._conn.commit()
        except Exception as e:
            log.warning(f"[orders][create] falha: {e}")

        if self.csv_enable:
            try:
                with open(self._orders_csv, "a", newline="", encoding="utf-8") as f:
                    w = csv.writer(f)
                    w.writerow([
                        ts,
                        live_order.order_id,
                        live_order.ex_name,
                        live_order.pair,
                        live_order.side,
                        live_order.symbol_local,
                        live_order.price_local,
                        live_order.amount,
                        live_order.status,
                    ])
            except Exception as e:
                log.warning(f"[orders.csv] falha: {e}")

    def record_order_cancel(self, live_order) -> None:
        ts = time.time()
        try:
            self._conn.execute(
                "UPDATE orders SET ts=?, status=? WHERE id=?",
                (ts, "canceled", str(live_order.order_id)),
            )
            self._conn.commit()
        except Exception as e:
            log.warning(f"[orders][cancel] falha: {e}")

        if self.csv_enable:
            try:
                with open(self._orders_csv, "a", newline="", encoding="utf-8") as f:
                    w = csv.writer(f)
                    w.writerow([
                        ts,
                        live_order.order_id,
                        live_order.ex_name,
                        live_order.pair,
                        live_order.side,
                        live_order.symbol_local,
                        live_order.price_local,
                        live_order.amount,
                        "canceled",
                    ])
            except Exception as e:
                log.warning(f"[orders.csv] falha: {e}")

    def record_paper_order(self, payload: Dict[str, Any]) -> None:
        ts = time.time()
        oid = str(payload.get("id") or f"paper_{int(ts * 1000)}")
        try:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO paper_orders
                (id, ts, pair, strategy, side, risk_percentage, qty, notional_usdt, cycle_id, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    oid,
                    ts,
                    str(payload.get("pair") or ""),
                    str(payload.get("strategy") or ""),
                    str(payload.get("side") or ""),
                    float(payload.get("risk_percentage") or 0.0),
                    float(payload.get("qty") or 0.0),
                    float(payload.get("computed_notional") or 0.0),
                    str(payload.get("cycle_id") or ""),
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
            self._conn.commit()
        except Exception as e:
            log.warning(f"[paper_orders] falha: {e}")

    def record_fill(self, data: Dict[str, Any]) -> None:
        """
        data: {id, ex_name, pair, side, symbol_local, price_local, price_usdt, amount, fee, info}
        """
        ts = time.time()
        try:
            self._conn.execute(
                """
                INSERT INTO fills (id, ts, ex_name, pair, side, symbol_local,
                                   price_local, price_usdt, amount, fee, info)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(data.get("id") or ""),
                    ts,
                    str(data.get("ex_name") or ""),
                    str(data.get("pair") or ""),
                    str(data.get("side") or ""),
                    str(data.get("symbol_local") or ""),
                    float(data.get("price_local") or 0.0),
                    float(data.get("price_usdt") or 0.0),
                    float(data.get("amount") or 0.0),
                    float(data.get("fee") or 0.0),
                    json.dumps(data.get("info") or {}, ensure_ascii=False),
                ),
            )
            self._conn.commit()
        except Exception as e:
            log.warning(f"[fills][insert] falha: {e}")

        if self.csv_enable:
            try:
                with open(self._fills_csv, "a", newline="", encoding="utf-8") as f:
                    w = csv.writer(f)
                    w.writerow([
                        ts,
                        data.get("id") or "",
                        data.get("ex_name") or "",
                        data.get("pair") or "",
                        data.get("side") or "",
                        data.get("symbol_local") or "",
                        float(data.get("price_local") or 0.0),
                        float(data.get("price_usdt") or 0.0),
                        float(data.get("amount") or 0.0),
                        float(data.get("fee") or 0.0),
                        json.dumps(data.get("info") or {}, ensure_ascii=False),
                    ])
            except Exception as e:
                log.warning(f"[fills.csv] falha: {e}")

    # ------------------------------------------------------------------
    # API pública — leitura (útil para painel / debug / API)

    def get_last_fills(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Retorna os últimos fills (mais recentes primeiro).
        """
        try:
            cur = self._conn.cursor()
            cur.execute(
                """
                SELECT id, ts, ex_name, pair, side, symbol_local,
                       price_local, price_usdt, amount, fee, info
                FROM fills
                ORDER BY ts DESC
                LIMIT ?
                """,
                (int(limit),),
            )
            rows = cur.fetchall()
            out: List[Dict[str, Any]] = []
            for r in rows:
                try:
                    info = r["info"]
                    try:
                        info = json.loads(info) if info else {}
                    except Exception:
                        info = {"raw": info}
                    out.append(
                        {
                            "id": r["id"],
                            "ts": r["ts"],
                            "ex_name": r["ex_name"],
                            "pair": r["pair"],
                            "side": r["side"],
                            "symbol_local": r["symbol_local"],
                            "price_local": r["price_local"],
                            "price_usdt": r["price_usdt"],
                            "amount": r["amount"],
                            "fee": r["fee"],
                            "info": info,
                        }
                    )
                except Exception:
                    continue
            return out
        except Exception as e:
            log.warning(f"[fills][select] falha: {e}")
            return []

    def get_last_events(self, limit: int = 100, event_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Retorna últimos eventos da tabela event_log.
        Se event_type for fornecido, filtra por type.
        """
        try:
            cur = self._conn.cursor()
            if event_type:
                cur.execute(
                    """
                    SELECT ts, type, payload
                    FROM event_log
                    WHERE type = ?
                    ORDER BY ts DESC
                    LIMIT ?
                    """,
                    (event_type, int(limit)),
                )
            else:
                cur.execute(
                    """
                    SELECT ts, type, payload
                    FROM event_log
                    ORDER BY ts DESC
                    LIMIT ?
                    """,
                    (int(limit),),
                )
            rows = cur.fetchall()
            out: List[Dict[str, Any]] = []
            for r in rows:
                try:
                    payload = r["payload"]
                    try:
                        payload = json.loads(payload) if payload else {}
                    except Exception:
                        payload = {"raw": payload}
                    out.append(
                        {
                            "ts": r["ts"],
                            "type": r["type"],
                            "payload": payload,
                        }
                    )
                except Exception:
                    continue
            return out
        except Exception as e:
            log.warning(f"[event_log][select] falha: {e}")
            return []

    def get_open_orders(self, limit: int = 200) -> List[Dict[str, Any]]:
        """
        Retorna ordens com status diferente de 'canceled'/'closed'.
        Útil para painel/verificação rápida.
        """
        try:
            cur = self._conn.cursor()
            cur.execute(
                """
                SELECT id, ts, ex_name, pair, side, symbol_local,
                       price_local, amount, status
                FROM orders
                WHERE COALESCE(LOWER(status), '') NOT IN ('canceled','closed')
                ORDER BY ts DESC
                LIMIT ?
                """,
                (int(limit),),
            )
            rows = cur.fetchall()
            return [
                {
                    "id": r["id"],
                    "ts": r["ts"],
                    "ex_name": r["ex_name"],
                    "pair": r["pair"],
                    "side": r["side"],
                    "symbol_local": r["symbol_local"],
                    "price_local": r["price_local"],
                    "amount": r["amount"],
                    "status": r["status"],
                }
                for r in rows
            ]
        except Exception as e:
            log.warning(f"[orders][open_select] falha: {e}")
            return []

    def get_order_by_id(self, order_id: str) -> Optional[Dict[str, Any]]:
        """
        Busca uma ordem específica pelo id.
        """
        try:
            cur = self._conn.cursor()
            cur.execute(
                """
                SELECT id, ts, ex_name, pair, side, symbol_local,
                       price_local, amount, status
                FROM orders
                WHERE id = ?
                """,
                (str(order_id),),
            )
            r = cur.fetchone()
            if not r:
                return None
            return {
                "id": r["id"],
                "ts": r["ts"],
                "ex_name": r["ex_name"],
                "pair": r["pair"],
                "side": r["side"],
                "symbol_local": r["symbol_local"],
                "price_local": r["price_local"],
                "amount": r["amount"],
                "status": r["status"],
            }
        except Exception as e:
            log.warning(f"[orders][get_by_id] falha: {e}")
            return None

    # ------------------------------------------------------------------
    # Encerramento

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass
