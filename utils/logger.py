# utils/logger.py
# Console humano + arquivo detalhado (com rotação)
# - get_user_logger(...) -> imprime mensagens simples no terminal (anti-flood opcional)
# - get_logger(...)      -> grava logs técnicos detalhados no arquivo

import logging
import os
import sys
import time
from logging.handlers import RotatingFileHandler
from typing import Optional, Dict

try:
    from colorama import init as colorama_init, Fore, Style
    colorama_init(autoreset=True)
    _COLORAMA = True
except Exception:
    _COLORAMA = False

_CONFIGURED = False
_DETAIL_HANDLER: Optional[logging.Handler] = None
_CONSOLE_HANDLER: Optional[logging.Handler] = None

# ----------------------------- formatters -----------------------------

class HumanConsoleFormatter(logging.Formatter):
    """Formato amigável para o usuário no terminal (leve e com cor opcional)."""
    def __init__(self):
        super().__init__(datefmt="%Y-%m-%d %H:%M:%S")
        if _COLORAMA:
            self._map = {
                "DEBUG": Fore.CYAN + Style.BRIGHT,
                "INFO": Fore.GREEN + Style.BRIGHT,
                "WARNING": Fore.YELLOW + Style.BRIGHT,
                "ERROR": Fore.RED + Style.BRIGHT,
                "CRITICAL": Fore.MAGENTA + Style.BRIGHT,
            }
        else:
            self._map = {}

    def format(self, record: logging.LogRecord) -> str:
        lvl = record.levelname
        if self._map:
            lvl = f"{self._map.get(record.levelname, '')}{record.levelname}{Style.RESET_ALL}"
        fmt = f"%(asctime)s [{lvl}] %(message)s"
        return logging.Formatter(fmt=fmt, datefmt="%Y-%m-%d %H:%M:%S").format(record)


class DetailedFileFormatter(logging.Formatter):
    """Formato completo para arquivo detalhado."""
    def __init__(self):
        super().__init__(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

# ----------------------------- filtros -----------------------------

class DedupFilter(logging.Filter):
    """
    Suprime mensagens idênticas dentro de uma janela (em segundos).
    Útil para evitar flood do tipo 'Ocorreu um erro no ciclo...' a cada tick.
    """
    def __init__(self, window_sec: float):
        super().__init__()
        self.window = max(0.0, float(window_sec))
        self._last: Dict[str, float] = {}

    def filter(self, record: logging.LogRecord) -> bool:
        if self.window <= 0:
            return True
        key = f"{record.levelno}:{record.getMessage()}"
        now = time.monotonic()
        last = self._last.get(key, 0.0)
        if now - last < self.window:
            return False
        self._last[key] = now
        return True

# ----------------------------- helpers -----------------------------

def _ensure_dir(path: str):
    try:
        d = os.path.dirname(os.path.abspath(path))
        if d:
            os.makedirs(d, exist_ok=True)
    except Exception:
        pass

def _derive_detailed_name(filename: str) -> str:
    """
    Gera um nome para o arquivo detalhado a partir do 'filename' principal.
    Ex.: './logs/arbit.log' -> './logs/arbit_detail.txt'
    """
    base, ext = os.path.splitext(filename)
    if not ext:
        ext = ".log"
    return f"{base}_detail.txt"

def _mute_noisy_libs():
    """
    Reduz ruído padrão de libs de rede/IO.
    Chamado dentro de configure_logging().
    """
    noisy = [
        "ccxt",
        "asyncio",
        "aiohttp",
        "aiohttp.client",
        "urllib3",
        "websockets",
        "charset_normalizer",
    ]
    for name in noisy:
        lg = logging.getLogger(name)
        lg.setLevel(logging.WARNING)
        # Evita handlers próprios dessas libs (normalmente não há, mas por via das dúvidas)
        for h in list(lg.handlers):
            try:
                lg.removeHandler(h)
            except Exception:
                pass

# ----------------------------- configuração -----------------------------

def configure_logging(
    level: str = "INFO",
    filename: Optional[str] = None,
    rotate_mb: int = 10,
    *,
    detailed_filename: Optional[str] = None,
    console_level: str = "INFO",
    file_level: str = "DEBUG",
    console_dedup_sec: Optional[float] = None,   # anti-flood opcional no console
):
    """
    Configura dois canais:
      - Console (humano): nível `console_level` (padrão INFO), formato simples.
        Anti-flood opcional por `console_dedup_sec` (ou env ARBIT_CONSOLE_DEDUP_SEC).
      - Arquivo detalhado (rotativo): nível `file_level` (padrão DEBUG), formato completo.

    Compatibilidade: parâmetros antigos (level, filename, rotate_mb) continuam válidos.
    Se `detailed_filename` não for informado e `filename` existir, derivamos '<nome>_detail.txt'.
    """
    global _CONFIGURED, _DETAIL_HANDLER, _CONSOLE_HANDLER

    # Valor do anti-flood via env, se não passado
    if console_dedup_sec is None:
        try:
            env_val = os.getenv("ARBIT_CONSOLE_DEDUP_SEC", "").strip()
            console_dedup_sec = float(env_val) if env_val else 0.0
        except Exception:
            console_dedup_sec = 0.0

    if _CONFIGURED:
        # Apenas ajusta níveis se já configurado
        if _CONSOLE_HANDLER:
            _CONSOLE_HANDLER.setLevel(getattr(logging, console_level.upper(), logging.INFO))
        if _DETAIL_HANDLER:
            _DETAIL_HANDLER.setLevel(getattr(logging, file_level.upper(), logging.DEBUG))
        return

    # Não queremos que tudo propague para o root e polua o console.
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.DEBUG)  # root alto; controlamos por handler

    # 1) Console humano
    ch = logging.StreamHandler(stream=sys.stdout)
    ch.setLevel(getattr(logging, console_level.upper(), logging.INFO))
    ch.setFormatter(HumanConsoleFormatter())
    # Anti-flood opcional
    try:
        dedup_sec = float(console_dedup_sec or 0.0)
    except Exception:
        dedup_sec = 0.0
    if dedup_sec > 0:
        ch.addFilter(DedupFilter(dedup_sec))
    _CONSOLE_HANDLER = ch

    # 2) Arquivo detalhado (rotativo)
    detail_path = None
    if detailed_filename:
        detail_path = detailed_filename
    elif filename:
        detail_path = _derive_detailed_name(filename)
    # Se nenhum arquivo passado, ainda assim criamos um detalhado padrão.
    if not detail_path:
        detail_path = "./logs/arbit_detail.txt"

    _ensure_dir(detail_path)
    fh = RotatingFileHandler(
        detail_path,
        maxBytes=int(max(1, rotate_mb)) * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    fh.setLevel(getattr(logging, file_level.upper(), logging.DEBUG))
    fh.setFormatter(DetailedFileFormatter())
    _DETAIL_HANDLER = fh

    # Silencia libs ruidosas
    _mute_noisy_libs()

    # Importante: não anexamos handlers ao ROOT para evitar duplicação/acúmulo.
    # Os loggers serão configurados individualmente por get_logger() e get_user_logger().

    _CONFIGURED = True

# ----------------------------- fábricas de logger -----------------------------

def _has_handler(logger: logging.Logger, target: logging.Handler) -> bool:
    return any(h is target for h in logger.handlers)

def get_logger(name: str) -> logging.Logger:
    """
    Logger técnico (arquivo detalhado). Não escreve no console.
    """
    global _DETAIL_HANDLER
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    if _DETAIL_HANDLER and not _has_handler(logger, _DETAIL_HANDLER):
        logger.addHandler(_DETAIL_HANDLER)
    return logger

def get_user_logger(name: str) -> logging.Logger:
    """
    Logger humano (console). Não escreve no arquivo detalhado.
    Use para mensagens simples que o usuário final lê no terminal.
    """
    global _CONSOLE_HANDLER
    lname = f"user.{name}" if not name.startswith("user.") else name
    logger = logging.getLogger(lname)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if _CONSOLE_HANDLER and not _has_handler(logger, _CONSOLE_HANDLER):
        logger.addHandler(_CONSOLE_HANDLER)
    return logger
