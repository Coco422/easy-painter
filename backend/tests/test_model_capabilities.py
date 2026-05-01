from app.api import routes
from app.core.config import Settings


def test_default_public_models_include_reference_image_capabilities():
    models = Settings(public_models_json="").public_models
    by_id = {item["id"]: item for item in models}

    assert by_id["gpt-image-2-b"]["supports_reference_image"] is True
    assert by_id["gpt-image-2-c"]["supports_reference_image"] is False
    assert by_id["grok-4.1-image"]["supports_reference_image"] is True
    assert by_id["grok-4.1-image"]["supported_sizes"] == [
        "1024x1024",
        "1280x720",
        "1792x1024",
        "720x1280",
        "1024x1792",
    ]
    assert by_id["doubao-seedream-5-0-260128"]["supports_reference_image"] is True


def test_public_models_json_fills_known_reference_image_capability():
    settings = Settings(
        public_models_json='[{"id":"gpt-image-2-c","label":"GPT-Image-2 C","enabled":true}]',
    )

    [model] = settings.public_models

    assert model["supports_reference_image"] is False


def test_public_models_json_fills_known_supported_sizes():
    settings = Settings(
        public_models_json='[{"id":"grok-imagine-image","label":"Grok Imagine","enabled":true}]',
    )

    [model] = settings.public_models

    assert model["supported_sizes"] == ["1024x1024", "1280x720", "1792x1024", "720x1280", "1024x1792"]


def test_public_models_json_allows_explicit_reference_image_capability():
    settings = Settings(
        public_models_json=(
            '[{"id":"custom-image","label":"Custom","enabled":true,'
            '"supports_reference_image":false,"supported_sizes":["1024x1024"]}]'
        ),
    )

    [model] = settings.public_models

    assert model["supports_reference_image"] is False
    assert model["supported_sizes"] == ["1024x1024"]


def test_default_upstream_timeout_allows_slow_image_models():
    assert Settings().upstream_timeout_seconds == 700


def test_empty_model_config_table_does_not_fall_back_to_env(monkeypatch):
    monkeypatch.setattr(routes, "load_models_from_db", lambda db: [])

    settings = Settings(
        public_models_json='[{"id":"fallback-model","label":"Fallback","enabled":true}]',
    )

    assert routes._load_models(object(), settings) == []
