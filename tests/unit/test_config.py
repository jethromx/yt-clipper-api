from yt_clipper.config import Settings


def test_settings_splits_csv_environment_values() -> None:
    settings = Settings(api_keys="first, second", cors_origins="http://localhost:3000")

    assert settings.api_keys == ["first", "second"]
    assert settings.cors_origins == ["http://localhost:3000"]
