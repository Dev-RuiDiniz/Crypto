from __future__ import annotations

import json
import sqlite3
import time
from datetime import datetime
from typing import Any, Optional

from flask import Blueprint, jsonify, request, g

from api.auth import extract_auth_context

trading_config_bp = Blueprint("trading_config", __name__)


class ValidationError(RuntimeError):
    def __init__(self, message: str, details: list[dict[str, str]]):
        super().__init__(message)
        self.details = details


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _error(status: int, error: str, message: str, details: Optional[list[dict[str, str]]] = None):
    return jsonify({"error": error, "message": message, "details": details or [], "correlationId": g.correlation_id}), status


def _authorize(tenant_id: str, required_roles: set[str]):
    ctx = extract_auth_context(request)
    if not ctx:
        return None, _error(401, "UNAUTHORIZED", "Authentication required")
    if ctx.tenant_id != tenant_id:
        return None, _error(403, "FORBIDDEN", "Tenant access denied")
    if required_roles and not (ctx.roles & required_roles):
        return None, _error(403, "FORBIDDEN", "Insufficient role")
    return ctx, None


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(g.db_path)
    conn.row_factory = sqlite3.Row
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
    CREATE TABLE IF NOT EXISTS trading_pairs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tenant_id TEXT NOT NULL,
        exchange TEXT NOT NULL,
        symbol TEXT NOT NULL,
        base TEXT,
        quote TEXT,
        enabled INTEGER NOT NULL DEFAULT 1,
        deleted_at TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(tenant_id, exchange, symbol)
    )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS pair_spread_config (
        tenant_id TEXT NOT NULL,
        symbol TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1,
        percent REAL NOT NULL DEFAULT 1.0,
        side_policy TEXT NOT NULL DEFAULT 'BOTH',
        repricing_interval_ms INTEGER,
        updated_at TEXT NOT NULL,
        PRIMARY KEY(tenant_id, symbol)
    )
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS tenant_risk_config (
        tenant_id TEXT PRIMARY KEY,
        max_percent_per_trade REAL NOT NULL DEFAULT 0,
        max_absolute_per_trade REAL NOT NULL DEFAULT 0,
        max_open_orders_per_symbol INTEGER NOT NULL DEFAULT 0,
        max_exposure_per_symbol REAL NOT NULL DEFAULT 0,
        kill_switch_enabled INTEGER NOT NULL DEFAULT 0,
        updated_at TEXT NOT NULL
    )
    """)


def _audit(conn: sqlite3.Connection, *, tenant_id: str, action: str, resource_type: str, resource_id: str, user_id: str, metadata: dict[str, Any]):
    conn.execute(
        """
        INSERT INTO audit_logs(tenant_id, action, resource_type, resource_id, user_id, created_at, metadata)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (tenant_id, action, resource_type, resource_id, user_id, _now_iso(), json.dumps(metadata, ensure_ascii=False)),
    )


def _bump_config(conn: sqlite3.Connection, reason: str, updated_by: str):
    now = _now_iso()
    conn.execute("INSERT OR IGNORE INTO config_version(id, version, updated_at, updated_by, reason) VALUES (1, 1, ?, 'system', 'bootstrap')", (now,))
    conn.execute("UPDATE config_version SET version = version + 1, updated_at = ?, updated_by = ?, reason = ? WHERE id = 1", (now, updated_by, reason))


def _parse_pair_id(raw: str) -> int:
    try:
        return int(raw)
    except Exception as exc:
        raise ValidationError("Invalid pair id", [{"field": "pairId", "issue": "not_integer"}]) from exc


def _get_pair(conn: sqlite3.Connection, tenant_id: str, pair_id: int):
    row = conn.execute("SELECT * FROM trading_pairs WHERE id = ? AND tenant_id = ? AND deleted_at IS NULL", (pair_id, tenant_id)).fetchone()
    if not row:
        raise ValidationError("Pair not found", [{"field": "pairId", "issue": "not_found"}])
    return row


@trading_config_bp.route("/api/tenants/<tenantId>/pairs", methods=["GET"])
def list_pairs(tenantId: str):
    _, err = _authorize(tenantId, {"ADMIN", "VIEWER"})
    if err:
        return err
    conn = _conn()
    rows = conn.execute("SELECT * FROM trading_pairs WHERE tenant_id = ? AND deleted_at IS NULL ORDER BY exchange, symbol", (tenantId,)).fetchall()
    return jsonify({"items": [dict(row) for row in rows]})


@trading_config_bp.route("/api/tenants/<tenantId>/pairs", methods=["POST"])
def create_pair(tenantId: str):
    ctx, err = _authorize(tenantId, {"ADMIN"})
    if err:
        return err
    payload = request.get_json(force=True, silent=True) or {}
    exchange = str(payload.get("exchange") or "").strip().lower()
    symbol = str(payload.get("symbol") or "").strip().upper().replace("-", "/")
    if not exchange or not symbol:
        return _error(400, "VALIDATION_ERROR", "Invalid payload", [{"field": "exchange/symbol", "issue": "required"}])
    now = _now_iso()
    conn = _conn()
    try:
        conn.execute(
            """INSERT INTO trading_pairs(tenant_id, exchange, symbol, base, quote, enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (tenantId, exchange, symbol, payload.get("base"), payload.get("quote"), 1 if bool(payload.get("enabled", True)) else 0, now, now),
        )
        conn.execute(
            """INSERT INTO config_pairs(symbol, enabled, strategy, risk_percentage, updated_at)
            VALUES (?, ?, 'StrategySpread', 0, ?)
            ON CONFLICT(symbol) DO UPDATE SET enabled=excluded.enabled, updated_at=excluded.updated_at""",
            (symbol, 1 if bool(payload.get("enabled", True)) else 0, time.time()),
        )
        _audit(conn, tenant_id=tenantId, action="CREATE", resource_type="PAIR", resource_id=symbol, user_id=ctx.user_id, metadata={"exchange": exchange, "enabled": bool(payload.get("enabled", True))})
        _bump_config(conn, f"PAIR_CREATED:{symbol}", ctx.user_id)
        conn.commit()
    except sqlite3.IntegrityError:
        return _error(409, "CONFLICT", "Pair already exists")
    row = conn.execute("SELECT * FROM trading_pairs WHERE tenant_id=? AND exchange=? AND symbol=?", (tenantId, exchange, symbol)).fetchone()
    return jsonify(dict(row)), 201


@trading_config_bp.route("/api/tenants/<tenantId>/pairs/<pairId>", methods=["PUT"])
def update_pair(tenantId: str, pairId: str):
    ctx, err = _authorize(tenantId, {"ADMIN"})
    if err:
        return err
    payload = request.get_json(force=True, silent=True) or {}
    try:
        pid = _parse_pair_id(pairId)
        conn = _conn()
        row = _get_pair(conn, tenantId, pid)
        enabled = 1 if bool(payload.get("enabled", row["enabled"])) else 0
        exchange = str(payload.get("exchange", row["exchange"])).strip().lower()
        now = _now_iso()
        conn.execute("UPDATE trading_pairs SET exchange=?, base=?, quote=?, enabled=?, updated_at=? WHERE id=?", (exchange, payload.get("base", row["base"]), payload.get("quote", row["quote"]), enabled, now, pid))
        conn.execute("UPDATE config_pairs SET enabled=?, updated_at=? WHERE symbol=?", (enabled, time.time(), row["symbol"]))
        _audit(conn, tenant_id=tenantId, action="UPDATE", resource_type="PAIR", resource_id=row["symbol"], user_id=ctx.user_id, metadata={"enabled": bool(enabled), "exchange": exchange})
        _bump_config(conn, f"PAIR_UPDATED:{row['symbol']}", ctx.user_id)
        conn.commit()
        updated = conn.execute("SELECT * FROM trading_pairs WHERE id=?", (pid,)).fetchone()
        return jsonify(dict(updated))
    except ValidationError as exc:
        return _error(404, "NOT_FOUND", str(exc), exc.details)


@trading_config_bp.route("/api/tenants/<tenantId>/pairs/<pairId>", methods=["DELETE"])
def delete_pair(tenantId: str, pairId: str):
    ctx, err = _authorize(tenantId, {"ADMIN"})
    if err:
        return err
    try:
        pid = _parse_pair_id(pairId)
        conn = _conn()
        row = _get_pair(conn, tenantId, pid)
        now = _now_iso()
        conn.execute("UPDATE trading_pairs SET enabled=0, deleted_at=?, updated_at=? WHERE id=?", (now, now, pid))
        conn.execute("UPDATE config_pairs SET enabled=0, updated_at=? WHERE symbol=?", (time.time(), row["symbol"]))
        _audit(conn, tenant_id=tenantId, action="DISABLE", resource_type="PAIR", resource_id=row["symbol"], user_id=ctx.user_id, metadata={})
        _bump_config(conn, f"PAIR_DISABLED:{row['symbol']}", ctx.user_id)
        conn.commit()
    except ValidationError as exc:
        return _error(404, "NOT_FOUND", str(exc), exc.details)
    return ("", 204)


@trading_config_bp.route("/api/tenants/<tenantId>/pairs/<pairId>/spread", methods=["GET"])
def get_pair_spread(tenantId: str, pairId: str):
    _, err = _authorize(tenantId, {"ADMIN", "VIEWER"})
    if err:
        return err
    try:
        pid = _parse_pair_id(pairId)
        conn = _conn()
        pair = _get_pair(conn, tenantId, pid)
        row = conn.execute("SELECT * FROM pair_spread_config WHERE tenant_id=? AND symbol=?", (tenantId, pair["symbol"])).fetchone()
        if not row:
            return jsonify({"enabled": True, "percent": 1.0, "sidePolicy": "BOTH", "repricingIntervalMs": None, "updatedAt": None})
        return jsonify({"enabled": bool(row["enabled"]), "percent": float(row["percent"]), "sidePolicy": row["side_policy"], "repricingIntervalMs": row["repricing_interval_ms"], "updatedAt": row["updated_at"]})
    except ValidationError as exc:
        return _error(404, "NOT_FOUND", str(exc), exc.details)


@trading_config_bp.route("/api/tenants/<tenantId>/pairs/<pairId>/spread", methods=["PUT"])
def put_pair_spread(tenantId: str, pairId: str):
    ctx, err = _authorize(tenantId, {"ADMIN"})
    if err:
        return err
    payload = request.get_json(force=True, silent=True) or {}
    percent = float(payload.get("percent") or 0)
    if percent < 0 or percent > 100:
        return _error(400, "VALIDATION_ERROR", "Invalid spread percent", [{"field": "percent", "issue": "out_of_range"}])
    try:
        pid = _parse_pair_id(pairId)
        conn = _conn()
        pair = _get_pair(conn, tenantId, pid)
        now = _now_iso()
        conn.execute(
            """INSERT INTO pair_spread_config(tenant_id, symbol, enabled, percent, side_policy, repricing_interval_ms, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(tenant_id, symbol) DO UPDATE SET enabled=excluded.enabled, percent=excluded.percent, side_policy=excluded.side_policy, repricing_interval_ms=excluded.repricing_interval_ms, updated_at=excluded.updated_at""",
            (tenantId, pair["symbol"], 1 if bool(payload.get("enabled", True)) else 0, percent, str(payload.get("sidePolicy") or "BOTH"), payload.get("repricingIntervalMs"), now),
        )
        _audit(conn, tenant_id=tenantId, action="UPDATE", resource_type="SPREAD", resource_id=pair["symbol"], user_id=ctx.user_id, metadata={"enabled": bool(payload.get("enabled", True)), "percent": percent})
        _bump_config(conn, f"SPREAD_UPDATED:{pair['symbol']}", ctx.user_id)
        conn.commit()
        return get_pair_spread(tenantId, pairId)
    except ValidationError as exc:
        return _error(404, "NOT_FOUND", str(exc), exc.details)


@trading_config_bp.route("/api/tenants/<tenantId>/pairs/<pairId>/arbitrage", methods=["GET"])
def get_pair_arbitrage(tenantId: str, pairId: str):
    _, err = _authorize(tenantId, {"ADMIN", "VIEWER"})
    if err:
        return err
    try:
        conn = _conn()
        pair = _get_pair(conn, tenantId, _parse_pair_id(pairId))
        row = conn.execute("SELECT * FROM arbitrage_config WHERE tenant_id=? AND symbol=?", (tenantId, pair["symbol"])).fetchone()
        if not row:
            return jsonify({"enabled": False, "exchangeA": "", "exchangeB": "", "thresholdPercent": 0.15, "thresholdAbsolute": 0.2, "maxTradeSize": 0, "cooldownMs": 0, "mode": "TWO_LEG"})
        return jsonify({"enabled": bool(row["enabled"]), "exchangeA": row["exchange_a"], "exchangeB": row["exchange_b"], "thresholdPercent": row["threshold_percent"], "thresholdAbsolute": row["threshold_absolute"], "maxTradeSize": row["max_trade_size"], "cooldownMs": row["cooldown_ms"], "mode": row["mode"]})
    except ValidationError as exc:
        return _error(404, "NOT_FOUND", str(exc), exc.details)


@trading_config_bp.route("/api/tenants/<tenantId>/pairs/<pairId>/arbitrage", methods=["PUT"])
def put_pair_arbitrage(tenantId: str, pairId: str):
    ctx, err = _authorize(tenantId, {"ADMIN"})
    if err:
        return err
    payload = request.get_json(force=True, silent=True) or {}
    try:
        conn = _conn()
        pair = _get_pair(conn, tenantId, _parse_pair_id(pairId))
        conn.execute(
            """INSERT INTO arbitrage_config(tenant_id, symbol, enabled, exchange_a, exchange_b, threshold_percent, threshold_absolute, max_trade_size, cooldown_ms, mode, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(tenant_id, symbol) DO UPDATE SET enabled=excluded.enabled, exchange_a=excluded.exchange_a, exchange_b=excluded.exchange_b, threshold_percent=excluded.threshold_percent, threshold_absolute=excluded.threshold_absolute, max_trade_size=excluded.max_trade_size, cooldown_ms=excluded.cooldown_ms, mode=excluded.mode, updated_at=excluded.updated_at""",
            (tenantId, pair["symbol"], 1 if bool(payload.get("enabled", False)) else 0, payload.get("exchangeA"), payload.get("exchangeB"), float(payload.get("thresholdPercent") or 0.15), float(payload.get("thresholdAbsolute") or 0.2), float(payload.get("maxTradeSize") or 0), int(payload.get("cooldownMs") or 0), str(payload.get("mode") or "TWO_LEG"), time.time()),
        )
        _audit(conn, tenant_id=tenantId, action="UPDATE", resource_type="ARBITRAGE", resource_id=pair["symbol"], user_id=ctx.user_id, metadata={"enabled": bool(payload.get("enabled", False))})
        _bump_config(conn, f"ARBITRAGE_UPDATED:{pair['symbol']}", ctx.user_id)
        conn.commit()
        return get_pair_arbitrage(tenantId, pairId)
    except ValidationError as exc:
        return _error(404, "NOT_FOUND", str(exc), exc.details)


@trading_config_bp.route("/api/tenants/<tenantId>/risk", methods=["GET"])
def get_global_risk(tenantId: str):
    _, err = _authorize(tenantId, {"ADMIN", "VIEWER"})
    if err:
        return err
    conn = _conn()
    row = conn.execute("SELECT * FROM tenant_risk_config WHERE tenant_id=?", (tenantId,)).fetchone()
    if not row:
        return jsonify({"maxPercentPerTrade": 0, "maxAbsolutePerTrade": 0, "maxOpenOrdersPerSymbol": 0, "maxExposurePerSymbol": 0, "killSwitchEnabled": False})
    return jsonify({"maxPercentPerTrade": row["max_percent_per_trade"], "maxAbsolutePerTrade": row["max_absolute_per_trade"], "maxOpenOrdersPerSymbol": row["max_open_orders_per_symbol"], "maxExposurePerSymbol": row["max_exposure_per_symbol"], "killSwitchEnabled": bool(row["kill_switch_enabled"]), "updatedAt": row["updated_at"]})


@trading_config_bp.route("/api/tenants/<tenantId>/risk", methods=["PUT"])
def put_global_risk(tenantId: str):
    ctx, err = _authorize(tenantId, {"ADMIN"})
    if err:
        return err
    payload = request.get_json(force=True, silent=True) or {}
    conn = _conn()
    now = _now_iso()
    conn.execute(
        """INSERT INTO tenant_risk_config(tenant_id, max_percent_per_trade, max_absolute_per_trade, max_open_orders_per_symbol, max_exposure_per_symbol, kill_switch_enabled, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(tenant_id) DO UPDATE SET max_percent_per_trade=excluded.max_percent_per_trade, max_absolute_per_trade=excluded.max_absolute_per_trade, max_open_orders_per_symbol=excluded.max_open_orders_per_symbol, max_exposure_per_symbol=excluded.max_exposure_per_symbol, kill_switch_enabled=excluded.kill_switch_enabled, updated_at=excluded.updated_at""",
        (tenantId, float(payload.get("maxPercentPerTrade") or 0), float(payload.get("maxAbsolutePerTrade") or 0), int(payload.get("maxOpenOrdersPerSymbol") or 0), float(payload.get("maxExposurePerSymbol") or 0), 1 if bool(payload.get("killSwitchEnabled", False)) else 0, now),
    )
    conn.execute("UPDATE bot_global_config SET kill_switch_enabled=?, updated_at=? WHERE id=1", (1 if bool(payload.get("killSwitchEnabled", False)) else 0, now))
    _audit(conn, tenant_id=tenantId, action="UPDATE", resource_type="RISK_GLOBAL", resource_id=tenantId, user_id=ctx.user_id, metadata={"killSwitchEnabled": bool(payload.get("killSwitchEnabled", False))})
    _bump_config(conn, "RISK_GLOBAL_UPDATED", ctx.user_id)
    conn.commit()
    return get_global_risk(tenantId)


@trading_config_bp.route("/api/tenants/<tenantId>/pairs/<pairId>/risk", methods=["GET"])
def get_pair_risk(tenantId: str, pairId: str):
    _, err = _authorize(tenantId, {"ADMIN", "VIEWER"})
    if err:
        return err
    try:
        conn = _conn()
        pair = _get_pair(conn, tenantId, _parse_pair_id(pairId))
        row = conn.execute("SELECT * FROM config_pairs WHERE symbol=?", (pair["symbol"],)).fetchone()
        if not row:
            return jsonify({"maxPercentPerTrade": 0, "maxAbsolutePerTrade": 0, "maxOpenOrdersPerSymbol": 0, "maxExposurePerSymbol": 0, "killSwitchEnabled": False})
        return jsonify({"maxPercentPerTrade": row["max_percent_per_trade"] or 0, "maxAbsolutePerTrade": row["max_absolute_per_trade"] or 0, "maxOpenOrdersPerSymbol": row["max_open_orders_per_symbol"] or 0, "maxExposurePerSymbol": row["max_exposure_per_symbol"] or 0, "killSwitchEnabled": bool(row["kill_switch_enabled"]), "updatedAt": row["updated_at"]})
    except ValidationError as exc:
        return _error(404, "NOT_FOUND", str(exc), exc.details)


@trading_config_bp.route("/api/tenants/<tenantId>/pairs/<pairId>/risk", methods=["PUT"])
def put_pair_risk(tenantId: str, pairId: str):
    ctx, err = _authorize(tenantId, {"ADMIN"})
    if err:
        return err
    payload = request.get_json(force=True, silent=True) or {}
    try:
        conn = _conn()
        pair = _get_pair(conn, tenantId, _parse_pair_id(pairId))
        conn.execute(
            """INSERT INTO config_pairs(symbol, enabled, strategy, risk_percentage, max_percent_per_trade, max_absolute_per_trade, max_open_orders_per_symbol, max_exposure_per_symbol, kill_switch_enabled, updated_at)
            VALUES (?, 1, 'StrategySpread', 0, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET max_percent_per_trade=excluded.max_percent_per_trade, max_absolute_per_trade=excluded.max_absolute_per_trade, max_open_orders_per_symbol=excluded.max_open_orders_per_symbol, max_exposure_per_symbol=excluded.max_exposure_per_symbol, kill_switch_enabled=excluded.kill_switch_enabled, updated_at=excluded.updated_at""",
            (pair["symbol"], float(payload.get("maxPercentPerTrade") or 0), float(payload.get("maxAbsolutePerTrade") or 0), int(payload.get("maxOpenOrdersPerSymbol") or 0), float(payload.get("maxExposurePerSymbol") or 0), 1 if bool(payload.get("killSwitchEnabled", False)) else 0, time.time()),
        )
        _audit(conn, tenant_id=tenantId, action="UPDATE", resource_type="RISK_PAIR", resource_id=pair["symbol"], user_id=ctx.user_id, metadata={"killSwitchEnabled": bool(payload.get("killSwitchEnabled", False))})
        _bump_config(conn, f"RISK_PAIR_UPDATED:{pair['symbol']}", ctx.user_id)
        conn.commit()
        return get_pair_risk(tenantId, pairId)
    except ValidationError as exc:
        return _error(404, "NOT_FOUND", str(exc), exc.details)


@trading_config_bp.route("/api/tenants/<tenantId>/pairs/<pairId>/runtime-status", methods=["GET"])
def get_pair_runtime_status(tenantId: str, pairId: str):
    _, err = _authorize(tenantId, {"ADMIN", "VIEWER"})
    if err:
        return err
    try:
        conn = _conn()
        pair = _get_pair(conn, tenantId, _parse_pair_id(pairId))
        runtime = conn.execute("SELECT * FROM runtime_status WHERE id = 1").fetchone()
        arb_state = conn.execute("SELECT * FROM arbitrage_state WHERE tenant_id=? AND symbol=?", (tenantId, pair["symbol"])).fetchone()
        heartbeat = float(runtime["last_heartbeat_at"] or 0) if runtime else 0
        stale = (time.time() - heartbeat) > 10 if heartbeat else True
        if not pair["enabled"]:
            bot_state, reason = "PAUSED", "PAIR_DISABLED"
        elif stale:
            bot_state, reason = "DEGRADED", "WORKER_STALE"
        else:
            bot_state, reason = "RUNNING", "OK"
        applied_at = runtime["last_applied_config_at"] if runtime else None
        return jsonify({
            "spreadAppliedAt": applied_at,
            "arbitrageAppliedAt": applied_at,
            "riskAppliedAt": applied_at,
            "marketdataSource": "POLL",
            "botState": bot_state,
            "reason": reason,
            "lastOpportunity": json.loads(arb_state["last_opportunity"]) if arb_state and arb_state["last_opportunity"] else None,
            "lastExecution": json.loads(arb_state["last_execution"]) if arb_state and arb_state["last_execution"] else None,
        })
    except ValidationError as exc:
        return _error(404, "NOT_FOUND", str(exc), exc.details)
