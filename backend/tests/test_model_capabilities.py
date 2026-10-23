import json

from app.api import routes
from app.core.config import Settings


def test_default_public_models_include_reference_image_capabilities():
    models = Settings(public_models_json="").public_models
    by_id = {item["id"]: item for item in models}

    assert by_id["gpt-image-2-b"]["supports_reference_image"] is True
    assert by_id["gpt-image-2-c"]["supports_reference_image"] is True
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

    assert model["supports_reference_image"] is True


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


def test_additional_upstreams_json_parses_provider_and_model_config():
    settings = Settings(
        public_models_json='[{"id":"primary-image","enabled":true}]',
        additional_upstreams_json=(
            '[{"name":"第三方","base_url":"https://images.example.com/v1",'
            '"api_key":"test-key","models":[{"id":"image-model",'
            '"supports_reference_image":true,"credit_cost":3}]}]'
        ),
    )

    [provider] = settings.additional_upstreams

    assert provider["name"] == "第三方"
    assert provider["models"][0]["id"] == "image-model"


def test_additional_upstreams_accept_explicit_size_routes_and_reject_invalid_routes():
    import pytest

    common = {
        "name": "4K 专用渠道",
        "base_url": "https://images.example.com/v1",
        "api_key": "test-key",
        "models": [{"id": "gpt-image-2", "fallback_for": "gpt-image-2", "route_for_sizes": ["4k"]}],
    }
    settings = Settings(
        public_models_json='[{"id":"gpt-image-2"}]',
        additional_upstreams_json=json.dumps([common]),
    )
    assert settings.additional_upstreams[0]["models"][0]["route_for_sizes"] == ["4k"]

    invalid_tier = {**common, "models": [{**common["models"][0], "route_for_sizes": ["8k"]}]}
    with pytest.raises(ValueError, match="1k, 2k or 4k"):
        Settings(
            public_models_json='[{"id":"gpt-image-2"}]',
            additional_upstreams_json=json.dumps([invalid_tier]),
        ).additional_upstreams

    missing_target = {**common, "models": [{"id": "gpt-image-2", "route_for_sizes": ["4k"]}]}
    with pytest.raises(ValueError, match="fallback_for"):
        Settings(
            public_models_json='[{"id":"gpt-image-2"}]',
            additional_upstreams_json=json.dumps([missing_target]),
        ).additional_upstreams


def test_gpt_image_4k_sizes_are_hidden_until_a_4k_route_is_configured(monkeypatch):
    from app.services import model_service

    no_route = Settings(public_models_json='[{"id":"gpt-image-2"}]')
    monkeypatch.setattr(model_service, "get_settings", lambda: no_route)
    sizes = model_service._public_model_sizes("gpt-image-2", [])
    assert "1024x1024" in sizes
    assert "2048x2048" in sizes
    assert "3840x2160" not in sizes
    assert "2160x3840" not in sizes

    routed = Settings(
        public_models_json='[{"id":"gpt-image-2"}]',
        additional_upstreams_json=json.dumps([{
            "name": "4K 专用渠道",
            "base_url": "https://images.example.com/v1",
            "api_key": "test-key",
            "models": [{"id": "gpt-image-2", "fallback_for": "gpt-image-2", "route_for_sizes": ["4k"]}],
        }]),
    )
    monkeypatch.setattr(model_service, "get_settings", lambda: routed)
    sizes = model_service._public_model_sizes("gpt-image-2", [])
    assert "3840x2160" in sizes
    assert "2160x3840" in sizes


def test_additional_upstreams_json_rejects_invalid_provider_shape():
    import pytest

    with pytest.raises(ValueError, match="JSON array"):
        Settings(additional_upstreams_json='{"name":"not-an-array"}').additional_upstreams

    with pytest.raises(ValueError, match="models"):
        Settings(additional_upstreams_json=(
            '[{"name":"third-party","base_url":"https://third-party.example.com/v1",'
            '"api_key":"test-key"}]'
        )).additional_upstreams


def test_additional_upstream_seed_is_additive_and_idempotent(monkeypatch):
    import json
    from sqlalchemy import create_engine, select, func
    from sqlalchemy.orm import Session
    from app.db.base import Base
    from app.db import init_db
    from app.models.upstream_provider import UpstreamProvider
    from app.models.model_config import ModelConfig

    engine = create_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    session = Session(engine)
    monkeypatch.setattr(init_db, 'SessionLocal', lambda: session)
    monkeypatch.setattr(
        init_db,
        'get_settings',
        lambda: Settings(
            upstream_base_url='https://self-hosted.example.com/v1',
            upstream_api_key='self-hosted-key',
            public_models_json='[{"id":"local-image","label":"自建模型"}]',
            additional_upstreams_json=json.dumps([{
                'name': '第三方',
                'base_url': 'https://third-party.example.com/v1',
                'api_key': 'third-party-key',
                'models': [{'id': 'remote-image', 'label': '第三方模型', 'credit_cost': 3}],
            }]),
        ),
    )
    try:
        init_db._seed_providers_and_models()
        init_db._seed_providers_and_models()

        providers = session.scalars(select(UpstreamProvider).order_by(UpstreamProvider.name)).all()
        models = session.scalars(select(ModelConfig).order_by(ModelConfig.id)).all()
        assert session.scalar(select(func.count()).select_from(UpstreamProvider)) == 2
        assert session.scalar(select(func.count()).select_from(ModelConfig)) == 2
        provider_by_name = {provider.name: provider for provider in providers}
        model_by_id = {model.id: model for model in models}
        assert provider_by_name['chatgpt2api（自建）'].base_url == 'https://self-hosted.example.com/v1'
        assert model_by_id['local-image'].provider_id == provider_by_name['chatgpt2api（自建）'].id
        assert model_by_id['remote-image'].provider_id == provider_by_name['第三方'].id
        assert model_by_id['remote-image'].credit_cost == 3
    finally:
        session.close()
        engine.dispose()


def test_syncing_public_models_disables_unlisted_rows_and_rebinds_configured_model(monkeypatch):
    import json
    from sqlalchemy import create_engine, select
    from sqlalchemy.orm import Session
    from app.db.base import Base
    from app.db import init_db
    from app.models.upstream_provider import UpstreamProvider
    from app.models.model_config import ModelConfig

    engine = create_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    session = Session(engine)
    old_provider = UpstreamProvider(name='旧渠道', base_url='https://old.example.com/v1', api_key='old-key')
    third_party = UpstreamProvider(name='第三方', base_url='https://third-party.example.com/v1', api_key='old-third-party-key')
    session.add_all([old_provider, third_party])
    session.flush()
    session.add_all([
        ModelConfig(id='legacy-model', provider_id=old_provider.id, label='旧模型', enabled=True),
        ModelConfig(id='gpt-image-2', provider_id=third_party.id, label='重复模型', enabled=True),
    ])
    session.commit()
    monkeypatch.setattr(init_db, 'SessionLocal', lambda: session)
    monkeypatch.setattr(
        init_db,
        'get_settings',
        lambda: Settings(
            upstream_base_url='https://self-hosted.example.com/v1',
            upstream_api_key='self-hosted-key',
            upstream_provider_name='chatgpt2api（自建）',
            public_models_json=(
                '[{"id":"primary-image","label":"主用绘图模型",'
                '"enabled":true,"upstream_model_id":"chatgpt2api-image-model",'
                '"supports_reference_image":true,"credit_cost":2}]'
            ),
            additional_upstreams_json=json.dumps([{
                'name': '第三方',
                'base_url': 'https://third-party.example.com/v1',
                'api_key': 'third-party-key',
                'models': [{
                    'id': 'primary-image',
                    'upstream_model_id': 'gpt-image-2',
                    'enabled': True,
                    'fallback_for': 'primary-image',
                    'supports_reference_image': True,
                }, {
                    'id': 'remote-image',
                    'label': '第三方独立模型',
                    'enabled': True,
                    'supports_reference_image': True,
                    'credit_cost': 6,
                    'credit_cost_by_size': {'1k': 6, '2k': 10, '4k': 15},
                }],
            }]),
            sync_public_models_from_env=True,
        ),
    )
    try:
        init_db._seed_providers_and_models()
        configured = session.get(ModelConfig, 'primary-image')
        legacy = session.get(ModelConfig, 'legacy-model')
        providers = session.scalars(select(UpstreamProvider)).all()
        primary = next(provider for provider in providers if provider.name == 'chatgpt2api（自建）')

        assert configured.provider_id == primary.id
        assert next(provider for provider in providers if provider.name == '旧渠道').base_url == 'https://old.example.com/v1'
        assert configured.enabled is True
        assert legacy.enabled is False
        assert session.scalar(select(ModelConfig.id).where(ModelConfig.enabled.is_(True))) == 'primary-image'
        assert len(providers) == 3
        remote = session.get(ModelConfig, 'remote-image')
        assert remote is not None and remote.enabled is True
        assert remote.provider_id == next(provider for provider in providers if provider.name == '第三方').id
        assert remote.credit_cost_by_size == {'1k': 6, '2k': 10, '4k': 15}
        assert session.get(ModelConfig, 'primary-image').provider_id != next(
            provider for provider in providers if provider.name == '第三方'
        ).id
    finally:
        session.close()
        engine.dispose()


def test_additional_upstream_model_can_be_configured_as_fallback_only():
    settings = Settings(
        public_models_json='[{"id":"primary-image","enabled":true}]',
        additional_upstreams_json=(
            '[{"name":"第三方","base_url":"https://images.example.com/v1",'
            '"api_key":"test-key","models":[{"id":"primary-image",'
            '"upstream_model_id":"gpt-image-2","enabled":true,'
            '"fallback_for":"primary-image"}]}]'
        ),
    )

    [provider] = settings.additional_upstreams
    [model] = provider["models"]

    assert model["fallback_for"] == "primary-image"
    assert model["upstream_model_id"] == "gpt-image-2"


def test_primary_model_config_can_map_to_a_provider_specific_model_name():
    settings = Settings(
        public_models_json=(
            '[{"id":"primary-image","upstream_model_id":"chatgpt2api-image-model",'
            '"enabled":true}]'
        ),
    )

    [model] = settings.public_models

    assert model["id"] == "primary-image"
    assert model["upstream_model_id"] == "chatgpt2api-image-model"


def test_public_model_config_accepts_size_pricing():
    settings = Settings(
        public_models_json=(
            '[{"id":"tiered-image","credit_cost":5,'
            '"credit_cost_by_size":{"1K":5,"2k":8,"4k":12}}]'
        ),
    )
    [model] = settings.public_models
    assert model["credit_cost_by_size"] == {"1k": 5, "2k": 8, "4k": 12}


def test_default_upstream_timeout_allows_slow_image_models():
    assert Settings().upstream_timeout_seconds == 700


def test_empty_model_config_table_does_not_fall_back_to_env(monkeypatch):
    monkeypatch.setattr(routes, "load_models_from_db", lambda db: [])

    settings = Settings(
        public_models_json='[{"id":"fallback-model","label":"Fallback","enabled":true}]',
    )

    assert routes._load_models(object(), settings) == []


def test_model_reference_limit_can_be_updated_and_exposed_without_restart():
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.db.base import Base
    from app.models.model_config import ModelConfig
    from app.api.admin_routes import UpdateModelRequest, admin_update_model
    from app.schemas.job import PublicModel
    from app.services.model_service import load_models_from_db

    engine = create_engine('sqlite+pysqlite:///:memory:')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(ModelConfig(id='gpt-image-2-b', label='test', provider_id='provider'))
        db.commit()
        assert PublicModel(**load_models_from_db(db)[0]).max_reference_images == 5
        for limit in [2, 12]:
            result = admin_update_model('gpt-image-2-b', UpdateModelRequest(max_reference_images=limit), db=db, _={})
            assert result.max_reference_images == limit
            assert PublicModel(**load_models_from_db(db)[0]).max_reference_images == limit


def test_model_reference_limit_is_positive_and_environment_seed_is_configurable():
    import pytest
    from pydantic import ValidationError
    from app.api.admin_routes import CreateModelRequest, UpdateModelRequest

    for invalid in [0, -1, 1.5]:
        with pytest.raises(ValidationError):
            UpdateModelRequest(max_reference_images=invalid)
        with pytest.raises(ValidationError):
            CreateModelRequest(id='test', provider_id='test', label='test', max_reference_images=invalid)
    [model] = Settings(public_models_json='[{"id":"gpt-image-2-b","max_reference_images":12}]').public_models
    assert model['max_reference_images'] == 12
