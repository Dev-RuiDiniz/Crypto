from app.paths import resolve_app_paths


def test_resolve_app_paths_contains_tradingbot_dir():
    paths = resolve_app_paths()
    assert paths.base_dir.name == "TradingBot"
    assert paths.db_path.name == "state.db"
    assert paths.data_dir.name == "data"
