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
from datetime import datetime
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
            CREATE TABLE IF NOT EXISTS tenants (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'ACTIVE',
                created_at TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS exchange_credentials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL,
                exchange TEXT NOT NULL,
                label TEXT NOT NULL,
                api_key_encrypted TEXT NOT NULL,
                api_secret_encrypted TEXT NOT NULL,
                passphrase_encrypted TEXT,
                last4 TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'ACTIVE',
                version INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                created_by TEXT,
                updated_by TEXT,
                FOREIGN KEY (tenant_id) REFERENCES tenants(id),
                UNIQUE (tenant_id, exchange, label)
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_exchange_credentials_tenant_exchange
            ON exchange_credentials (tenant_id, exchange)
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id TEXT NOT NULL,
                action TEXT NOT NULL,
                resource_type TEXT NOT NULL,
                resource_id TEXT NOT NULL,
                user_id TEXT,
                created_at TEXT NOT NULL,
                metadata TEXT,
                FOREIGN KEY (tenant_id) REFERENCES tenants(id)
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
                id INTEGER PRIMARY KEY CHECK (id = 1),
                worker_pid INTEGER,
                started_at REAL,
                last_heartbeat_at REAL,
                db_path TEXT,
                version TEXT,
                last_applied_config_version INTEGER,
                last_applied_config_at TEXT,
                last_applied_config_reason TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS config_version (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                version INTEGER NOT NULL,
                updated_at TEXT NOT NULL,
                updated_by TEXT,
                reason TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS bot_global_config (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                mode TEXT NOT NULL DEFAULT 'PAPER',
                loop_interval_ms INTEGER NOT NULL DEFAULT 2000,
                kill_switch_enabled INTEGER NOT NULL DEFAULT 0,
                max_positions INTEGER NOT NULL DEFAULT 1,
                max_daily_loss REAL NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            )
            """
        )
        global_cols = {
            str(r[1]).lower()
            for r in cur.execute("PRAGMA table_info(bot_global_config)").fetchall()
        }
        if "mode" not in global_cols:
            cur.execute("ALTER TABLE bot_global_config ADD COLUMN mode TEXT NOT NULL DEFAULT 'PAPER'")
        if "loop_interval_ms" not in global_cols:
            cur.execute("ALTER TABLE bot_global_config ADD COLUMN loop_interval_ms INTEGER NOT NULL DEFAULT 2000")
        if "kill_switch_enabled" not in global_cols:
            cur.execute("ALTER TABLE bot_global_config ADD COLUMN kill_switch_enabled INTEGER NOT NULL DEFAULT 0")
        if "max_positions" not in global_cols:
            cur.execute("ALTER TABLE bot_global_config ADD COLUMN max_positions INTEGER NOT NULL DEFAULT 1")
        if "max_daily_loss" not in global_cols:
            cur.execute("ALTER TABLE bot_global_config ADD COLUMN max_daily_loss REAL NOT NULL DEFAULT 0")
        if "updated_at" not in global_cols:
            cur.execute("ALTER TABLE bot_global_config ADD COLUMN updated_at TEXT")
            cur.execute(
                "UPDATE bot_global_config SET updated_at = ? WHERE COALESCE(updated_at, '') = ''",
                (datetime.utcnow().isoformat(timespec="seconds") + "Z",),
            )
        runtime_cols = {
            str(r[1]).lower()
            for r in cur.execute("PRAGMA table_info(runtime_status)").fetchall()
        }
        if "id" not in runtime_cols:
            cur.execute("ALTER TABLE runtime_status ADD COLUMN id INTEGER")
            cur.execute("UPDATE runtime_status SET id = 1 WHERE id IS NULL")
        if "last_applied_config_version" not in runtime_cols:
            cur.execute("ALTER TABLE runtime_status ADD COLUMN last_applied_config_version INTEGER")
        if "last_applied_config_at" not in runtime_cols:
            cur.execute("ALTER TABLE runtime_status ADD COLUMN last_applied_config_at TEXT")
        if "last_applied_config_reason" not in runtime_cols:
            cur.execute("ALTER TABLE runtime_status ADD COLUMN last_applied_config_reason TEXT")
        self.ensure_config_version_row()
        self.ensure_default_bot_global_config()
        self.ensure_default_tenant()
        self._conn.commit()

    def ensure_default_tenant(self) -> None:
        now_iso = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        self._conn.execute(
            """
            INSERT OR IGNORE INTO tenants(id, name, status, created_at)
            VALUES ('default', 'default', 'ACTIVE', ?)
            """,
            (now_iso,),
        )

    def ensure_config_version_row(self) -> None:
        now_iso = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        self._conn.execute(
            """
            INSERT OR IGNORE INTO config_version(id, version, updated_at, updated_by, reason)
            VALUES (1, 1, ?, 'system', 'bootstrap')
            """,
            (now_iso,),
        )

    def get_config_version(self) -> Dict[str, Any]:
        self.ensure_config_version_row()
        row = self._conn.execute(
            """
            SELECT id, version, updated_at, updated_by, reason
            FROM config_version
            WHERE id = 1
            """
        ).fetchone()
        if not row:
            return {
                "id": 1,
                "version": 1,
                "updated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                "updated_by": "system",
                "reason": "bootstrap",
            }
        return {
            "id": int(row["id"] if isinstance(row, sqlite3.Row) else row[0]),
            "version": int(row["version"] if isinstance(row, sqlite3.Row) else row[1]),
            "updated_at": str(row["updated_at"] if isinstance(row, sqlite3.Row) else row[2]),
            "updated_by": str((row["updated_by"] if isinstance(row, sqlite3.Row) else row[3]) or ""),
            "reason": str((row["reason"] if isinstance(row, sqlite3.Row) else row[4]) or ""),
        }

    def bump_config_version(self, reason: str, updated_by: str = "api") -> int:
        now_iso = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        safe_reason = str(reason or "config updated")
        safe_updated_by = str(updated_by or "api")
        with self._conn:
            self.ensure_config_version_row()
            self._conn.execute(
                """
                UPDATE config_version
                SET version = version + 1,
                    updated_at = ?,
                    updated_by = ?,
                    reason = ?
                WHERE id = 1
                """,
                (now_iso, safe_updated_by, safe_reason),
            )
            row = self._conn.execute("SELECT version FROM config_version WHERE id = 1").fetchone()
        return int((row["version"] if isinstance(row, sqlite3.Row) else row[0]) if row else 1)

    def ensure_default_bot_global_config(self) -> None:
        now_iso = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        self._conn.execute(
            """
            INSERT OR IGNORE INTO bot_global_config
            (id, mode, loop_interval_ms, kill_switch_enabled, max_positions, max_daily_loss, updated_at)
            VALUES (1, 'PAPER', 2000, 0, 1, 0, ?)
            """,
            (now_iso,),
        )

    def get_bot_global_config(self) -> Dict[str, Any]:
        self.ensure_default_bot_global_config()
        row = self._conn.execute(
            """
            SELECT id, mode, loop_interval_ms, kill_switch_enabled, max_positions, max_daily_loss, updated_at
            FROM bot_global_config
            WHERE id = 1
            """
        ).fetchone()
        if not row:
            return {
                "mode": "PAPER",
                "loop_interval_ms": 2000,
                "kill_switch_enabled": False,
                "max_positions": 1,
                "max_daily_loss": 0.0,
                "updated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            }
        return {
            "mode": str(row["mode"] if isinstance(row, sqlite3.Row) else row[1]).upper(),
            "loop_interval_ms": int((row["loop_interval_ms"] if isinstance(row, sqlite3.Row) else row[2]) or 2000),
            "kill_switch_enabled": bool((row["kill_switch_enabled"] if isinstance(row, sqlite3.Row) else row[3]) or 0),
            "max_positions": int((row["max_positions"] if isinstance(row, sqlite3.Row) else row[4]) or 1),
            "max_daily_loss": float((row["max_daily_loss"] if isinstance(row, sqlite3.Row) else row[5]) or 0.0),
            "updated_at": str((row["updated_at"] if isinstance(row, sqlite3.Row) else row[6]) or ""),
        }

    def upsert_bot_global_config(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        current = self.get_bot_global_config()
        mode = str(payload.get("mode") or current["mode"] or "PAPER").upper().strip()
        if mode not in ("PAPER", "LIVE"):
            mode = "PAPER"
        loop_interval_ms = int(payload.get("loop_interval_ms", current["loop_interval_ms"]))
        kill_switch_enabled = bool(payload.get("kill_switch_enabled", current["kill_switch_enabled"]))
        max_positions = int(payload.get("max_positions", current["max_positions"]))
        max_daily_loss = float(payload.get("max_daily_loss", current["max_daily_loss"]))
        updated_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"

        self._conn.execute(
            """
            INSERT INTO bot_global_config
            (id, mode, loop_interval_ms, kill_switch_enabled, max_positions, max_daily_loss, updated_at)
            VALUES (1, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                mode=excluded.mode,
                loop_interval_ms=excluded.loop_interval_ms,
                kill_switch_enabled=excluded.kill_switch_enabled,
                max_positions=excluded.max_positions,
                max_daily_loss=excluded.max_daily_loss,
                updated_at=excluded.updated_at
            """,
            (
                mode,
                max(100, loop_interval_ms),
                1 if kill_switch_enabled else 0,
                max(1, max_positions),
                max(0.0, max_daily_loss),
                updated_at,
            ),
        )
        self._conn.commit()
        return self.get_bot_global_config()

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
                INSERT INTO runtime_status(
                    id, worker_pid, started_at, last_heartbeat_at, db_path, version,
                    last_applied_config_version, last_applied_config_at, last_applied_config_reason
                )
                VALUES (1, ?, ?, ?, ?, ?, NULL, NULL, NULL)
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
                WHERE id = 1
                """,
                (float(time.time()), int(worker_pid)),
            )
            self._conn.commit()
        except Exception as e:
            log.warning(f"[runtime_status] heartbeat falha: {e}")

    def update_runtime_applied_config(self, config_version: int, applied_at: str, reason: str = "") -> None:
        try:
            self._conn.execute(
                """
                UPDATE runtime_status
                SET last_applied_config_version = ?,
                    last_applied_config_at = ?,
                    last_applied_config_reason = ?
                WHERE id = 1
                """,
                (int(config_version), str(applied_at), str(reason or "")),
            )
            self._conn.commit()
        except Exception as e:
            log.warning(f"[runtime_status] update applied config falha: {e}")

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
