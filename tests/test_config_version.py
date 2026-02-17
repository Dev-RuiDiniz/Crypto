import configparser
import tempfile
import unittest
from pathlib import Path

from core.monitors import MainMonitor
from core.state_store import StateStore


class ConfigVersionStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tmpdir.name) / "state.db")
        cfg = configparser.ConfigParser()
        cfg["GLOBAL"] = {"SQLITE_PATH": self.db_path, "CSV_ENABLE": "false"}
        self.state = StateStore(cfg)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_bump_config_version_should_create_and_increment(self):
        v1 = self.state.get_config_version()["version"]
        bumped = self.state.bump_config_version("test update", updated_by="test")
        v2 = self.state.get_config_version()["version"]

        self.assertGreaterEqual(v1, 1)
        self.assertEqual(bumped, v1 + 1)
        self.assertEqual(v2, v1 + 1)


class WorkerConfigReloadTests(unittest.TestCase):
    def test_worker_detects_version_change(self):
        class FakeState:
            def __init__(self):
                self.version = 1
                self.updated = []

            def get_config_version(self):
                return {"version": self.version, "reason": "unit-test"}

            def get_bot_global_config(self):
                return {"mode": "PAPER", "loop_interval_ms": 1000, "kill_switch_enabled": False, "max_positions": 1, "max_daily_loss": 0.0, "updated_at": ""}

            def get_bot_configs(self, enabled_only=True):
                return [{"pair": "BTC/USDT", "enabled": True}]

            def update_runtime_applied_config(self, config_version, applied_at, reason=""):
                self.updated.append((config_version, applied_at, reason))

        monitor = MainMonitor.__new__(MainMonitor)
        monitor.state = FakeState()
        monitor.use_config_file_pairs = False
        monitor.cfg_pairs = []
        monitor.pairs = []
        monitor.bot_configs = {}
        monitor._bot_config_cache_ts = {}
        monitor.global_config = {}
        monitor.last_seen_config_version = 0
        monitor.last_applied_at = ""
        monitor._last_global_updated_at = ""
        monitor.ex_hub = type("Hub", (), {"mode": "PAPER"})()
        monitor.risk = type("Risk", (), {"max_open_per_pair_ex": 1, "kill_dd_pct": 0.0})()
        monitor.loop_interval_ms = 1000

        monitor._reload_configs_if_needed(force=True)
        self.assertEqual(monitor.last_seen_config_version, 1)
        self.assertEqual(monitor.pairs, ["BTC/USDT"])
        self.assertEqual(len(monitor.state.updated), 1)

        monitor.state.version = 2
        monitor._reload_configs_if_needed(force=False)
        self.assertEqual(monitor.last_seen_config_version, 2)
        self.assertEqual(len(monitor.state.updated), 2)


if __name__ == "__main__":
    unittest.main()
