import time

from api import handlers


def test_normalize_db_path_returns_absolute(tmp_path):
    rel_db = tmp_path / "nested" / "state.db"
    normalized = handlers._normalize_db_path(str(rel_db))
    assert normalized == str(rel_db.resolve())
    assert rel_db.parent.exists()


def test_classify_worker_status_down_and_stale(monkeypatch):
    now = 1_000.0
    monkeypatch.setattr(time, "time", lambda: now)

    assert handlers._classify_worker_status(None, stale_after_sec=30) == "down"
    assert handlers._classify_worker_status(0.0, stale_after_sec=30) == "down"
    assert handlers._classify_worker_status(now - 10, stale_after_sec=30) == "ok"
    assert handlers._classify_worker_status(now - 31, stale_after_sec=30) == "stale"
