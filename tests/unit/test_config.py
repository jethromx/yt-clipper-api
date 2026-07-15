from yt_clipper.config import Settings


def test_settings_splits_csv_environment_values() -> None:
    settings = Settings(api_keys="first, second", cors_origins="http://localhost:3000")

    assert settings.api_keys == ["first", "second"]
    assert settings.cors_origins == ["http://localhost:3000"]


def test_settings_expose_anthropic_defaults() -> None:
    from yt_clipper.config import Settings

    settings = Settings()

    assert settings.anthropic_api_key is None
    assert settings.anthropic_model == "claude-haiku-4-5"


def test_settings_expose_allowed_models() -> None:
    from yt_clipper.config import Settings

    settings = Settings()

    assert settings.anthropic_model in settings.anthropic_allowed_models
    assert "claude-haiku-4-5" in settings.anthropic_allowed_models
    assert "claude-sonnet-5" in settings.anthropic_allowed_models
    assert "claude-opus-4-8" in settings.anthropic_allowed_models
