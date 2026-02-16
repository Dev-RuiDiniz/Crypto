# api/server.py
import os
import sys
import logging
from datetime import datetime
from typing import Any, Dict

from flask import Flask, jsonify, request, send_from_directory, abort

# -----------------------------------------------------------------------------
# LOGGING BÁSICO
# -----------------------------------------------------------------------------
logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="[API] %(asctime)s %(levelname)s:%(name)s:%(message)s",
    )

# -----------------------------------------------------------------------------
# RESOLUÇÃO DE DIRETÓRIOS (DEV / PYINSTALLER onedir / PYINSTALLER onefile)
# -----------------------------------------------------------------------------
def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _get_work_dir() -> str:
    """
    Diretório de trabalho onde o usuário executa o sistema.
    - Dev: raiz do projeto (um nível acima de api/)
    - PyInstaller: pasta onde está o .exe
    """
    if _is_frozen():
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _get_bundle_dir() -> str:
    """
    Diretório interno do bundle:
    - Dev: igual ao work_dir
    - PyInstaller onefile: sys._MEIPASS
    - PyInstaller onedir: normalmente igual ao work_dir
    """
    if _is_frozen() and hasattr(sys, "_MEIPASS"):
        return os.path.abspath(getattr(sys, "_MEIPASS"))
    return _get_work_dir()


WORK_DIR = _get_work_dir()
BUNDLE_DIR = _get_bundle_dir()

# Frontend: tente primeiro no WORK_DIR (onedir / arquivos ao lado do exe).
# Se não existir, tente no BUNDLE_DIR (onefile com add-data).
FRONTEND_DIR_WORK = os.path.join(WORK_DIR, "frontend", "src")
FRONTEND_DIR_BUNDLE = os.path.join(BUNDLE_DIR, "frontend", "src")

FRONTEND_DIR = FRONTEND_DIR_WORK if os.path.isdir(FRONTEND_DIR_WORK) else FRONTEND_DIR_BUNDLE

# Data: geralmente precisa existir no WORK_DIR (onde ficam dumps / arquivos gerados)
DATA_DIR = os.path.join(WORK_DIR, "data")

logger.info("==================================================")
logger.info("INICIANDO SERVIDOR ARBIT")
logger.info("FROZEN: %s", _is_frozen())
logger.info("WORK_DIR: %s", WORK_DIR)
logger.info("BUNDLE_DIR: %s", BUNDLE_DIR)
logger.info("FRONTEND_DIR_WORK: %s", FRONTEND_DIR_WORK)
logger.info("FRONTEND_DIR_BUNDLE: %s", FRONTEND_DIR_BUNDLE)
logger.info("FRONTEND_DIR (em uso): %s", FRONTEND_DIR)
logger.info("DATA_DIR: %s", DATA_DIR)
logger.info("DIRETÓRIO ATUAL (cwd): %s", os.getcwd())
logger.info("==================================================")


# -----------------------------------------------------------------------------
# IMPORTA HANDLERS
# -----------------------------------------------------------------------------
try:
    from . import handlers
except Exception:
    import handlers  # type: ignore


# -----------------------------------------------------------------------------
# CRIAÇÃO DO APP FLASK
# -----------------------------------------------------------------------------
# Observação:
# - Você está servindo arquivos diretamente de frontend/src (index.html, App.js, styles, etc).
# - static_folder só é útil se você realmente tiver uma pasta /static dentro do frontend.
# - Mantemos, mas protegemos com fallback.
STATIC_DIR = os.path.join(FRONTEND_DIR, "static")
STATIC_DIR = STATIC_DIR if os.path.isdir(STATIC_DIR) else None

app = Flask(
    __name__,
    static_folder=STATIC_DIR,
    static_url_path="/static" if STATIC_DIR else None,
)


# -----------------------------------------------------------------------------
# HELPERS
# -----------------------------------------------------------------------------
def _safe_send(base_dir: str, filename: str):
    """
    Envia arquivo do diretório base (send_from_directory).
    """
    return send_from_directory(base_dir, filename)


def _index_exists() -> bool:
    return os.path.isfile(os.path.join(FRONTEND_DIR, "index.html"))


# -----------------------------------------------------------------------------
# ROTAS FRONTEND
# -----------------------------------------------------------------------------
@app.route("/")
def index():
    """
    Serve o HTML principal do painel.
    """
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
    """
    Serve arquivos da pasta data (WORK_DIR/data).
    """
    if not os.path.isdir(DATA_DIR):
        abort(404)
    return send_from_directory(DATA_DIR, filename)


# Serve qualquer arquivo do frontend por caminho.
# Ex: /App.js, /styles/main.css, /components/Dashboard.js, etc.
@app.route("/<path:filename>")
def frontend_files(filename: str):
    """
    Serve qualquer arquivo dentro de frontend/src (JS, CSS, imagens…).
    - Se existir, retorna o arquivo.
    - Se não existir e o index.html existir, retorna index.html (fallback SPA).
    - Se nenhum existir, 404.
    """
    full_path = os.path.join(FRONTEND_DIR, filename)

    # Segurança básica: não permitir traversal
    norm = os.path.normpath(full_path)
    if not norm.startswith(os.path.normpath(FRONTEND_DIR)):
        return ("Caminho inválido.", 400)

    if os.path.isfile(full_path):
        return _safe_send(FRONTEND_DIR, filename)

    # fallback SPA: rotas do front retornam index.html
    if _index_exists():
        return _safe_send(FRONTEND_DIR, "index.html")

    return (
        f"Arquivo não encontrado no frontend: {filename}\n"
        f"FRONTEND_DIR: {FRONTEND_DIR}\n"
        "E index.html também não existe.",
        404,
    )


# -----------------------------------------------------------------------------
# ROTAS API
# -----------------------------------------------------------------------------
@app.route("/api/ping")
def api_ping():
    return jsonify({"ok": True, "ts": datetime.utcnow().isoformat(timespec="seconds") + "Z"})


@app.route("/api/balances")
def api_balances():
    data = handlers.get_balances()
    return jsonify(data)


@app.route("/api/orders")
def api_orders():
    state = request.args.get("state", "pending")
    data = handlers.get_orders(state)
    return jsonify(data)


@app.route("/api/mids")
def api_mids():
    pair = request.args.get("pair", "")
    data = handlers.get_mids(pair)
    return jsonify(data)


@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    if request.method == "GET":
        data = handlers.get_config()
        return jsonify(data)

    payload: Dict[str, Any] = request.get_json(force=True, silent=True) or {}
    ok, msg = handlers.update_config(payload)
    status = 200 if ok else 400
    return jsonify({"ok": ok, "message": msg}), status


@app.route("/api/debug")
def api_debug():
    data = handlers.debug_snapshot()
    return jsonify(data)


@app.route("/api/events")
def api_events():
    """
    Retorna a lista de eventos humanos para o frontend exibir.
    """
    data = handlers.get_events()
    return jsonify(data)


# -----------------------------------------------------------------------------
# FUNÇÃO main() — CHAMADA PELO run_arbit.py
# -----------------------------------------------------------------------------
def main(host: str = "127.0.0.1", port: int = 8000):
    """
    Ponto de entrada usado por run_arbit.py:
        from api import server
        server.main()
    """
    logger.info("🚀 Iniciando servidor ARBIT em http://%s:%s", host, port)
    logger.info("📋 Rotas disponíveis:")
    for rule in sorted(app.url_map.iter_rules(), key=lambda r: str(r.rule)):
        methods = ",".join(sorted(m for m in rule.methods if m not in {"HEAD", "OPTIONS"}))
        logger.info("   %-35s %s", rule.rule, methods or "(GET)")

    # MUITO IMPORTANTE no exe:
    # - use_reloader=False evita spawn duplicado e múltiplas abas/instâncias.
    app.run(host=host, port=port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
