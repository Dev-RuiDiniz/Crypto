import logging
from pathlib import Path
from types import ModuleType, SimpleNamespace

from app import launcher
import bot


def test_bot_parse_args_accepts_named_config():
    args = bot.parse_args(["--config", "config.txt", "--db-path", "state.db"])
    assert args.config == "config.txt"
    assert args.db_path == "state.db"


def test_launcher_run_worker_rewrites_argv(monkeypatch):
    monkeypatch.setattr(
        launcher,
        "parse_args",
        lambda: SimpleNamespace(
            run_api=False,
            run_worker=True,
            config="config.txt",
            db_path="state.db",
            host="127.0.0.1",
            port=8000,
            open_logs=False,
            no_browser=True,
        ),
    )

    captured = {}

    fake_bot = ModuleType("bot")

    def fake_main():
        import sys

        captured["argv"] = sys.argv[:]

    fake_bot.main = fake_main

    import sys

    monkeypatch.setitem(sys.modules, "bot", fake_bot)
    rc = launcher.main()

    assert rc == 0
    assert captured["argv"] == [
        captured["argv"][0],
        "--config",
        "config.txt",
        "--db-path",
        "state.db",
    ]


def test_launcher_worker_command_uses_config_flag(monkeypatch):
    paths = SimpleNamespace(
        data_dir=Path("data"),
        log_dir=Path("logs"),
        db_path=Path("data/state.db"),
    )
    monkeypatch.setattr(
        launcher,
        "parse_args",
        lambda: SimpleNamespace(
            run_api=False,
            run_worker=False,
            config="config.txt",
            db_path=None,
            host="127.0.0.1",
            port=8000,
            open_logs=False,
            no_browser=True,
        ),
    )
    monkeypatch.setattr(launcher, "resolve_app_paths", lambda: paths)
    monkeypatch.setattr(launcher, "ensure_runtime_dirs", lambda _: None)
    monkeypatch.setattr(launcher, "_configure_launcher_logger", lambda _: logging.getLogger("test"))
    monkeypatch.setattr(launcher, "_resolve_port", lambda host, port, logger: port)
    monkeypatch.setattr(launcher, "current_python", lambda: "python")

    class FakeProc:
        returncode = 0

        def poll(self):
            return None

    calls = []

    def fake_spawn(cmd, cwd=None, env=None):
        calls.append(cmd)
        return FakeProc()

    monkeypatch.setattr(launcher, "spawn_process", fake_spawn)
    monkeypatch.setattr(launcher, "terminate_process", lambda proc: None)
    monkeypatch.setattr(launcher, "_wait_api_ready", lambda *args, **kwargs: (_ for _ in ()).throw(KeyboardInterrupt()))

    rc = launcher.main()

    assert rc == 0
    assert calls[1][:5] == ["python", "-m", "bot", "--config", "config.txt"]
