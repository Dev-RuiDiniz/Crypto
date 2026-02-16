# utils/__init__.py
# Marca 'utils' como pacote Python e reexporta utilidades comuns.

from .logger import get_logger, configure_logging

__all__ = ["get_logger", "configure_logging"]
