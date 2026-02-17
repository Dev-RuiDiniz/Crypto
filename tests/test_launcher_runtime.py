import logging

from app import launcher


def test_resolve_port_keeps_preferred_when_available(monkeypatch):
    monkeypatch.setattr(launcher, "_is_port_available", lambda host, port: port == 8000)
    port = launcher._resolve_port("127.0.0.1", 8000, logging.getLogger("test"))
    assert port == 8000


def test_resolve_port_fallback_range(monkeypatch):
    monkeypatch.setattr(launcher, "_is_port_available", lambda host, port: port == 5003)
    port = launcher._resolve_port("127.0.0.1", 8000, logging.getLogger("test"))
    assert port == 5003
