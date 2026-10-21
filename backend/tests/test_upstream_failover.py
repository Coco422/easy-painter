from types import SimpleNamespace

import pytest

from app.services import tasks
from app.services.model_service import FailoverProvider, ProviderConfig
from app.services.upstream import UpstreamServiceError


def _provider(base_url: str) -> ProviderConfig:
    return ProviderConfig(
        base_url=base_url,
        api_key="test-key",
        timeout_seconds=30,
        default_size="auto",
        default_quality="high",
        default_output_format="png",
        default_output_compression=85,
        default_background="auto",
        default_moderation="auto",
    )


def test_explicit_primary_rejection_uses_configured_fallback(monkeypatch):
    calls = []
    result = object()

    class FakeClient:
        def __init__(self, config):
            self.config = config

        def generate_image(self, **request):
            calls.append((self.config["base_url"], request))
            if self.config["base_url"] == "https://primary.example.com/v1":
                raise UpstreamServiceError("unsupported model", retryable=False, failover_safe=True)
            return result

    fallback = FailoverProvider(
        name="备用",
        config=_provider("https://fallback.example.com/v1"),
        model_id="gpt-image-2",
    )
    monkeypatch.setattr(tasks, "UpstreamImageClient", FakeClient)
    monkeypatch.setattr(tasks, "load_primary_upstream_model_id", lambda model_id: "chatgpt2api-image")
    monkeypatch.setattr(tasks, "load_failover_providers_for_model", lambda db, model_id: [fallback])
    job = SimpleNamespace(model="gpt-image-2", prompt="draw a lake", size="1024x1024", aspect_ratio="1:1")

    actual = tasks._generate_with_failover(
        object(),
        job=job,
        provider_config={"base_url": "https://primary.example.com/v1", "api_key": "test-key"},
        reference_images=[],
    )

    assert actual is result
    assert [call[0] for call in calls] == [
        "https://primary.example.com/v1",
        "https://fallback.example.com/v1",
    ]
    assert calls[0][1]["model"] == "chatgpt2api-image"
    assert calls[1][1]["model"] == "gpt-image-2"


def test_primary_read_timeout_does_not_retry_on_fallback(monkeypatch):
    fallback_loads = []

    class FakeClient:
        def __init__(self, config):
            pass

        def generate_image(self, **request):
            raise UpstreamServiceError("timeout", retryable=True, failover_safe=False)

    monkeypatch.setattr(tasks, "UpstreamImageClient", FakeClient)
    monkeypatch.setattr(tasks, "load_primary_upstream_model_id", lambda model_id: model_id)
    monkeypatch.setattr(
        tasks,
        "load_failover_providers_for_model",
        lambda db, model_id: fallback_loads.append(model_id) or [],
    )
    job = SimpleNamespace(model="gpt-image-2", prompt="draw a lake", size="1024x1024", aspect_ratio="1:1")

    with pytest.raises(UpstreamServiceError, match="timeout"):
        tasks._generate_with_failover(
            object(),
            job=job,
            provider_config={"base_url": "https://primary.example.com/v1", "api_key": "test-key"},
            reference_images=[],
        )

    assert fallback_loads == []


def test_fallback_skipped_when_reference_image_limit_is_exceeded(monkeypatch):
    calls = []

    class FakeClient:
        def __init__(self, config):
            self.config = config

        def generate_image(self, **request):
            calls.append(self.config["base_url"])
            if self.config["base_url"] == "https://primary.example.com/v1":
                raise UpstreamServiceError("unavailable", retryable=False, failover_safe=True)
            return object()

    fallback = FailoverProvider(
        name="备用",
        config=_provider("https://fallback.example.com/v1"),
        model_id="gpt-image-2",
        max_reference_images=1,
    )
    monkeypatch.setattr(tasks, "UpstreamImageClient", FakeClient)
    monkeypatch.setattr(tasks, "load_primary_upstream_model_id", lambda model_id: model_id)
    monkeypatch.setattr(tasks, "load_failover_providers_for_model", lambda db, model_id: [fallback])
    job = SimpleNamespace(model="gpt-image-2", prompt="edit", size="1024x1024", aspect_ratio="1:1")

    with pytest.raises(UpstreamServiceError, match="unavailable"):
        tasks._generate_with_failover(
            object(),
            job=job,
            provider_config={"base_url": "https://primary.example.com/v1", "api_key": "test-key"},
            reference_images=[object(), object()],
        )

    assert calls == ["https://primary.example.com/v1"]


@pytest.mark.parametrize("supports_reference_image,expected_limit", [(True, 1), (False, 0)])
def test_fallback_loader_preserves_reference_capabilities(monkeypatch, supports_reference_image, expected_limit):
    import json
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.core.config import Settings
    from app.db.base import Base
    from app.models.model_config import ModelConfig
    from app.models.upstream_provider import UpstreamProvider
    from app.services import model_service

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        primary = UpstreamProvider(name="primary", base_url="https://primary.example.com/v1", api_key="test-key")
        backup = UpstreamProvider(name="backup", base_url="https://fallback.example.com/v1", api_key="db-key")
        db.add_all([primary, backup])
        db.flush()
        db.add(ModelConfig(id="gpt-image-2", provider_id=primary.id, label="image"))
        db.commit()
        config = Settings(
            public_models_json='[{"id":"gpt-image-2"}]',
            additional_upstreams_json=json.dumps([{
                "name": "backup", "base_url": backup.base_url, "api_key": "env-key",
                "models": [{"id": "gpt-image-2", "fallback_for": "gpt-image-2",
                            "supports_reference_image": supports_reference_image, "max_reference_images": 1}],
            }]),
        )
        monkeypatch.setattr(model_service, "get_settings", lambda: config)
        [fallback] = model_service.load_failover_providers_for_model(db, "gpt-image-2")
        assert fallback.max_reference_images == expected_limit
        assert fallback.config.api_key == "db-key"
        assert fallback.model_id == "gpt-image-2"
    engine.dispose()
