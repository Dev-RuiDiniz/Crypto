from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import socket
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from app.paths import ensure_runtime_dirs, resolve_app_paths
from app.processes import current_python, spawn_process, terminate_process
from app.version import APP_VERSION


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="TradingBot local launcher")
    parser.add_argument("--port", type=int, default=8000, help="Porta local da API/dashboard")
    parser.add_argument("--host", default="127.0.0.1", help="Host local da API")
    parser.add_argument("--config", default="config.txt", help="Arquivo config.txt legado")
    parser.add_argument("--no-browser", action="store_true", help="Não abrir navegador automaticamente")
    parser.add_argument("--open-logs", action="store_true", help="Abre a pasta de logs no Explorer e sai")
    parser.add_argument("--db-path", default=None, help=argparse.SUPPRESS)
    parser.add_argument("--run-api", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--run-worker", action="store_true", help=argparse.SUPPRESS)
    return parser.parse_args()


def _configure_launcher_logger(log_file: Path) -> logging.Logger:
    logger = logging.getLogger("launcher")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter("[LAUNCHER] %(asctime)s %(levelname)s:%(message)s")
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(formatter)
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setFormatter(formatter)

    logger.addHandler(sh)
    logger.addHandler(fh)
    return logger


def _wait_api_ready(base_url: str, timeout_sec: float, logger: logging.Logger) -> dict:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(f"{base_url}/api/health", timeout=2) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
                if payload.get("status") == "ok":
                    return payload
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            time.sleep(0.5)
            continue
    raise TimeoutError("API healthcheck timeout")


def _is_port_available(host: str, port: int) -> bool:
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex((host, port)) != 0


def _resolve_port(host: str, preferred_port: int, logger: logging.Logger) -> int:
    if _is_port_available(host, preferred_port):
        return preferred_port
    logger.warning("Porta %s ocupada. Buscando alternativa no range 5000-5100.", preferred_port)
    for port in range(5000, 5101):
        if _is_port_available(host, port):
            logger.info("Porta alternativa selecionada: %s", port)
            return port
    raise RuntimeError("Nenhuma porta livre encontrada no range 5000-5100")


def _open_logs_folder(log_dir: Path, logger: logging.Logger) -> None:
    if os.name == "nt":
        os.startfile(str(log_dir))  # type: ignore[attr-defined]
    else:
        logger.warning("Ação 'Abrir pasta de logs' é suportada apenas no Windows.")


def main() -> int:
    args = parse_args()

    if args.run_api:
        from api.server import main as api_main

        api_main(host=args.host, port=args.port, db_path=args.db_path)
        return 0
    if args.run_worker:
        from bot import main as worker_main
        worker_argv = [sys.argv[0], "--config", args.config]
        if args.db_path:
            worker_argv.extend(["--db-path", str(args.db_path)])
        original_argv = sys.argv
        try:
            sys.argv = worker_argv
            worker_main()
        finally:
            sys.argv = original_argv
        return 0

    repo_root = Path(__file__).resolve().parents[1]

    paths = resolve_app_paths()
    ensure_runtime_dirs(paths)

    logger = _configure_launcher_logger(paths.log_dir / "app.log")
    logger.info("[BOOT] app_version=%s", APP_VERSION)
    logger.info("[BOOT] DATA_DIR=%s", paths.data_dir)
    logger.info("[BOOT] LOG_DIR=%s", paths.log_dir)
    logger.info("[BOOT] DB_PATH=%s", paths.db_path.resolve())

    if args.open_logs:
        _open_logs_folder(paths.log_dir, logger)
        return 0

    selected_port = _resolve_port(args.host, args.port, logger)

    env = os.environ.copy()
    env["TRADINGBOT_LOG_DIR"] = str(paths.log_dir)
    env["TRADINGBOT_APP_VERSION"] = APP_VERSION
    env["TRADINGBOT_WORKER_LOG_FILE"] = str(paths.log_dir / "worker.log")

    py_bin = current_python()
    if getattr(sys, "frozen", False):
        api_cmd = [py_bin, "--run-api", "--host", args.host, "--port", str(selected_port), "--db-path", str(paths.db_path)]
        worker_cmd = [py_bin, "--run-worker", "--config", args.config, "--db-path", str(paths.db_path)]
    else:
        api_cmd = [
            py_bin,
            "-m",
            "api.server",
            "--host",
            args.host,
            "--port",
            str(selected_port),
            "--db-path",
            str(paths.db_path),
        ]
        worker_cmd = [
            py_bin,
            "-m",
            "bot",
            "--config",
            args.config,
            "--db-path",
            str(paths.db_path),
        ]

    logger.info("[BOOT] Starting API: %s", " ".join(api_cmd))
    api_proc = spawn_process(api_cmd, cwd=repo_root, env=env)
    logger.info("[BOOT] Starting Worker: %s", " ".join(worker_cmd))
    worker_proc = spawn_process(worker_cmd, cwd=repo_root, env=env)

    base_url = f"http://{args.host}:{selected_port}"
    try:
        health = _wait_api_ready(base_url, timeout_sec=45, logger=logger)
        logger.info("API health OK: %s", health)
        if not args.no_browser:
            webbrowser.open(f"{base_url}/")
            logger.info("Dashboard opened at %s/", base_url)

        while True:
            if api_proc.poll() is not None:
                logger.error("API process exited with code=%s", api_proc.returncode)
                return 1
            if worker_proc.poll() is not None:
                logger.error("Worker process exited with code=%s", worker_proc.returncode)
                return 1
            time.sleep(2)
    except KeyboardInterrupt:
        logger.info("Launcher interrupted by user")
        return 0
    except Exception as exc:
        logger.error("Fatal launcher error: %s", exc)
        return 1
    finally:
        terminate_process(api_proc)
        terminate_process(worker_proc)


if __name__ == "__main__":
    raise SystemExit(main())
