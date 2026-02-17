from pathlib import Path

import pytest

from app import pathing


def test_resolve_config_path_prefers_data_dir(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    work_dir = tmp_path / "work"
    data_dir.mkdir()
    work_dir.mkdir()
    (data_dir / "config.txt").write_text("[GLOBAL]\n", encoding="utf-8")
    (work_dir / "config.txt").write_text("[GLOBAL]\n", encoding="utf-8")

    monkeypatch.setattr(pathing, "get_data_dir", lambda: data_dir)
    monkeypatch.setattr(pathing, "get_work_dir", lambda: work_dir)

    resolved = pathing.resolve_config_path("config.txt", must_exist=True)
    assert resolved.path == (data_dir / "config.txt").resolve()


def test_resolve_config_path_reports_attempts(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    work_dir = tmp_path / "work"
    data_dir.mkdir()
    work_dir.mkdir()

    monkeypatch.setattr(pathing, "get_data_dir", lambda: data_dir)
    monkeypatch.setattr(pathing, "get_work_dir", lambda: work_dir)

    with pytest.raises(pathing.ConfigResolutionError) as exc:
        pathing.resolve_config_path("config.txt", must_exist=True)

    assert exc.value.tried_paths == [
        (data_dir / "config.txt").resolve(),
        (work_dir / "config.txt").resolve(),
    ]


def test_ensure_default_config_in_data_dir_copies_from_work_dir(monkeypatch, tmp_path):
    data_dir = tmp_path / "data"
    work_dir = tmp_path / "work"
    data_dir.mkdir()
    work_dir.mkdir()
    (work_dir / "config.txt").write_text("[GLOBAL]\nMODE=PAPER\n", encoding="utf-8")

    monkeypatch.setattr(pathing, "get_data_dir", lambda: data_dir)
    monkeypatch.setattr(pathing, "get_work_dir", lambda: work_dir)

    copied = pathing.ensure_default_config_in_data_dir()

    assert copied == (data_dir / "config.txt").resolve()
    assert (data_dir / "config.txt").read_text(encoding="utf-8").startswith("[GLOBAL]")
