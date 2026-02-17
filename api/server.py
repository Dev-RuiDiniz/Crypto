# api/server.py
import argparse
import logging
import os
import sys
from datetime import datetime
from typing import Any, Dict, Optional

from flask import Flask, jsonify, request, send_from_directory, abort, g

from app.version import APP_VERSION
from api.exchange_credentials_api import exchange_credentials_bp
from api.notifications_api import notifications_bp

logger = logging.getLogger(__name__)


def _setup_logging() -> None:
    log_dir = os.getenv("TRADINGBOT_LOG_DIR", "").strip()
    handlers = [logging.StreamHandler(sys.stdout)]
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)
        handlers.append(logging.FileHandler(os.path.join(log_dir, "api.log"), encoding="utf-8"))
    logging.basicConfig(
        level=logging.INFO,
        format="[API] %(asctime)s %(levelname)s:%(name)s:%(message)s",
        handlers=handlers,
        force=True,
    )


_setup_logging()


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _get_work_dir() -> str:
    if _is_frozen():
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _get_bundle_dir() -> str:
    if _is_frozen() and hasattr(sys, "_MEIPASS"):
        return os.path.abspath(getattr(sys, "_MEIPASS"))
    return _get_work_dir()


def _select_frontend_dir() -> str:
    candidates = [
        os.path.join(_get_work_dir(), "frontend", "build"),
        os.path.join(_get_bundle_dir(), "frontend", "build"),
        os.path.join(_get_work_dir(), "frontend", "src"),
        os.path.join(_get_bundle_dir(), "frontend", "src"),
    ]
    for candidate in candidates:
        if os.path.isfile(os.path.join(candidate, "index.html")):
            return candidate
    return candidates[-1]


def _resolve_data_dir() -> str:
    local_appdata = os.getenv("LOCALAPPDATA", "").strip()
    if local_appdata:
        return os.path.join(local_appdata, "TradingBot", "data")
    return os.path.join(_get_work_dir(), "data")


WORK_DIR = _get_work_dir()
BUNDLE_DIR = _get_bundle_dir()
FRONTEND_DIR = _select_frontend_dir()
DATA_DIR = _resolve_data_dir()

logger.info("==================================================")
logger.info("INICIANDO SERVIDOR ARBIT")
logger.info("FROZEN: %s", _is_frozen())
logger.info("WORK_DIR: %s", WORK_DIR)
logger.info("FRONTEND_DIR (em uso): %s", FRONTEND_DIR)
logger.info("DATA_DIR: %s", DATA_DIR)
logger.info("==================================================")

try:
    from . import handlers
except Exception:
    import handlers  # type: ignore

STATIC_DIR = os.path.join(FRONTEND_DIR, "static")
STATIC_DIR = STATIC_DIR if os.path.isdir(STATIC_DIR) else None

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="/static" if STATIC_DIR else None)
app.register_blueprint(exchange_credentials_bp)
app.register_blueprint(notifications_bp)


def _safe_send(base_dir: str, filename: str):
    return send_from_directory(base_dir, filename)




def _open_logs_dir() -> bool:
    log_dir = os.getenv("TRADINGBOT_LOG_DIR", "").strip()
    if not log_dir or not os.path.isdir(log_dir):
        return False
    if os.name == "nt":
        os.startfile(log_dir)  # type: ignore[attr-defined]
        return True
    return False

def _index_exists() -> bool:
    return os.path.isfile(os.path.join(FRONTEND_DIR, "index.html"))


@app.route("/")
def index():
    if _index_exists():
        return _safe_send(FRONTEND_DIR, "index.html")
    return (
        "<h1>ARBIT - Painel</h1>"
        "<p>Arquivo <b>frontend/src/index.html</b> não encontrado.</p>"
        f"<p>FRONTEND_DIR atual: <code>{FRONTEND_DIR}</code></p>",
        404,
    )


@app.route("/data/<path:filename>")
def data_files(filename: str):
    if not os.path.isdir(DATA_DIR):
        abort(404)
    return send_from_directory(DATA_DIR, filename)


@app.route("/<path:filename>")
def frontend_files(filename: str):
    full_path = os.path.join(FRONTEND_DIR, filename)
    norm = os.path.normpath(full_path)
    if not norm.startswith(os.path.normpath(FRONTEND_DIR)):
        return ("Caminho inválido.", 400)
    if os.path.isfile(full_path):
        return _safe_send(FRONTEND_DIR, filename)
    if _index_exists():
        return _safe_send(FRONTEND_DIR, "index.html")
    return (f"Arquivo não encontrado no frontend: {filename}\nFRONTEND_DIR: {FRONTEND_DIR}\n", 404)





@app.before_request
def attach_correlation_id():
    cid = (request.headers.get("X-Correlation-Id") or "").strip()
    if not cid:
        cid = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    g.correlation_id = cid
    g.db_path = handlers.get_effective_db_path()


@app.after_request
def add_correlation_id_header(response):
    correlation_id = getattr(g, "correlation_id", "")
    if correlation_id:
        response.headers["X-Correlation-Id"] = correlation_id
    return response

@app.route("/api/open-logs", methods=["POST"])
def api_open_logs():
    opened = _open_logs_dir()
    return jsonify({"ok": opened})


@app.route("/api/ping")
def api_ping():
    return jsonify({"ok": True, "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z"})


@app.route("/api/health")
def api_health():
    return jsonify(
        {
            "status": "ok",
            "app": "trading-bot",
            "version": APP_VERSION,
            "time": datetime.utcnow().isoformat(timespec="seconds") + "Z",
            "db_path": handlers.get_effective_db_path(),
            "pid": os.getpid(),
        }
    )


@app.route("/api/health/db")
def api_health_db():
    return jsonify(handlers.get_db_health())


@app.route("/api/health/worker")
def api_health_worker():
    return jsonify(handlers.get_worker_health())


@app.route("/api/config-status")
def api_config_status():
    return jsonify(handlers.get_config_status())


@app.route("/api/balances")
def api_balances():
    return jsonify(handlers.get_balances())


@app.route("/api/orders")
def api_orders():
    state = request.args.get("state", "pending")
    return jsonify(handlers.get_orders(state))


@app.route("/api/mids")
def api_mids():
    pair = request.args.get("pair", "")
    return jsonify(handlers.get_mids(pair))


@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    if request.method == "GET":
        return jsonify(handlers.get_config())
    payload: Dict[str, Any] = request.get_json(force=True, silent=True) or {}
    ok, msg = handlers.update_config(payload)
    return jsonify({"ok": ok, "message": msg}), (200 if ok else 400)


@app.route("/api/bot-config", methods=["GET", "POST"])
def api_bot_config():
    if request.method == "GET":
        return jsonify(handlers.get_bot_configs())
    payload: Dict[str, Any] = request.get_json(force=True, silent=True) or {}
    ok, msg = handlers.upsert_bot_config(payload)
    return jsonify({"ok": ok, "message": msg}), (200 if ok else 400)


@app.route("/api/bot-global-config", methods=["GET", "POST"])
def api_bot_global_config():
    if request.method == "GET":
        return jsonify(handlers.get_bot_global_config())
    payload: Dict[str, Any] = request.get_json(force=True, silent=True) or {}
    ok, msg = handlers.upsert_bot_global_config(payload)
    return jsonify({"ok": ok, "message": msg}), (200 if ok else 400)



@app.route("/api/arbitrage-config", methods=["GET", "POST"])
def api_arbitrage_config():
    tenant_id = request.headers.get("X-Tenant-Id", "default")
    if request.method == "GET":
        pair = request.args.get("pair", "")
        return jsonify(handlers.get_arbitrage_config(pair, tenant_id=tenant_id))
    payload: Dict[str, Any] = request.get_json(force=True, silent=True) or {}
    ok, msg = handlers.upsert_arbitrage_config(payload, tenant_id=tenant_id)
    return jsonify({"ok": ok, "message": msg}), (200 if ok else 400)


@app.route("/api/arbitrage-status")
def api_arbitrage_status():
    tenant_id = request.headers.get("X-Tenant-Id", "default")
    pair = request.args.get("pair", "")
    return jsonify(handlers.get_arbitrage_status(pair, tenant_id=tenant_id))

@app.route("/api/debug")
def api_debug():
    return jsonify(handlers.debug_snapshot())


@app.route("/api/events")
def api_events():
    return jsonify(handlers.get_events())



@app.route("/api/tenants/<tenantId>/risk/events")
def api_risk_events(tenantId: str):
    symbol = request.args.get("symbol", "")
    limit = int(request.args.get("limit", "50") or 50)
    return jsonify(handlers.get_risk_events(tenant_id=tenantId, symbol=symbol, limit=limit))

@app.route("/api/tenants/<tenantId>/metrics")
def api_tenant_metrics(tenantId: str):
    return jsonify(handlers.get_tenant_metrics(tenantId))


@app.route("/api/tenants/<tenantId>/go-live-checklist")
def api_go_live_checklist(tenantId: str):
    return jsonify(handlers.get_go_live_checklist(tenantId))


@app.route("/api/tenants/<tenantId>/marketdata/orderbook-status")
def api_marketdata_orderbook_status(tenantId: str):
    exchange = request.args.get("exchange", "")
    symbol = request.args.get("symbol", "")
    return jsonify(handlers.get_marketdata_orderbook_status(tenantId, exchange=exchange, symbol=symbol))


@app.errorhandler(500)
def on_internal_error(_):
    return jsonify({
        "error": "INTERNAL_ERROR",
        "message": "Unexpected error",
        "details": [],
        "correlationId": getattr(g, "correlation_id", ""),
    }), 500

def main(host: str = "127.0.0.1", port: int = 8000, db_path: Optional[str] = None):
    if db_path:
        handlers.set_db_path_override(db_path)
    logger.info("[BOOT] DB_PATH=%s", handlers.get_effective_db_path())
    logger.info("🚀 Iniciando servidor ARBIT em http://%s:%s", host, port)
    app.run(host=host, port=port, debug=False, use_reloader=False)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="API server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--db-path", default=None)
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    main(host=args.host, port=args.port, db_path=args.db_path)
