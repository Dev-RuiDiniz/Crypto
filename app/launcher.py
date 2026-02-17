from __future__ import annotations

import argparse
import json
import logging
import os
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


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]

    paths = resolve_app_paths()
    ensure_runtime_dirs(paths)

    logger = _configure_launcher_logger(paths.log_dir / "app.log")
    logger.info("[BOOT] app_version=%s", APP_VERSION)
    logger.info("[BOOT] DATA_DIR=%s", paths.data_dir)
    logger.info("[BOOT] LOG_DIR=%s", paths.log_dir)
    logger.info("[BOOT] DB_PATH=%s", paths.db_path.resolve())

    env = os.environ.copy()
    env["TRADINGBOT_LOG_DIR"] = str(paths.log_dir)
    env["TRADINGBOT_APP_VERSION"] = APP_VERSION
    env["TRADINGBOT_WORKER_LOG_FILE"] = str(paths.log_dir / "worker.log")

    py_bin = current_python()
    api_cmd = [
        py_bin,
        "-m",
        "api.server",
        "--host",
        args.host,
        "--port",
        str(args.port),
        "--db-path",
        str(paths.db_path),
    ]
    worker_cmd = [
        py_bin,
        "-m",
        "bot",
        args.config,
        "--db-path",
        str(paths.db_path),
    ]

    logger.info("[BOOT] Starting API: %s", " ".join(api_cmd))
    api_proc = spawn_process(api_cmd, cwd=repo_root, env=env)
    logger.info("[BOOT] Starting Worker: %s", " ".join(worker_cmd))
    worker_proc = spawn_process(worker_cmd, cwd=repo_root, env=env)

    base_url = f"http://{args.host}:{args.port}"
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
