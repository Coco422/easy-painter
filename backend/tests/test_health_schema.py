from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.services import health


def test_readiness_expected_schema_matches_latest_migration():
    migrations = Path(__file__).resolve().parents[1] / 'db' / 'migration'
    latest = max(int(path.name.split('__', 1)[0][1:]) for path in migrations.glob('V*__*.sql'))
    assert health.EXPECTED_FLYWAY_VERSION == str(latest)


@pytest.mark.parametrize('version,expected_status', [('8', 'ok'), ('7', 'degraded')])
def test_readiness_reports_actual_schema_compatibility(monkeypatch, version, expected_status):
    db = SimpleNamespace(execute=lambda statement: SimpleNamespace(scalar_one_or_none=lambda: version))
    redis = SimpleNamespace(ping=lambda: True, get=lambda key: 'heartbeat', ttl=lambda key: 30)
    monkeypatch.setattr(health, 'MinioStorageService', lambda: SimpleNamespace(check_ready=lambda: True))
    result = health.collect_core_health(db=db, redis_client=redis, settings=Settings())
    assert result['schema'] == {'status': expected_status, 'version': version, 'expected': '8'}
