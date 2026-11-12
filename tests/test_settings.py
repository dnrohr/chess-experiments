from counterfactual_chess.settings import Settings, load_settings, save_settings


def test_settings_roundtrip_and_corruption(tmp_path):
    path = tmp_path / "settings.json"
    assert load_settings(path) == Settings()
    settings = Settings("C:/Stockfish/stockfish.exe", 2, 128, 2.5)
    save_settings(settings, path)
    assert load_settings(path) == settings
    for contents in ('{"threads": 0}', 'bad', '{"seconds": "wrong"}'):
        path.write_text(contents)
        assert load_settings(path) == Settings()
