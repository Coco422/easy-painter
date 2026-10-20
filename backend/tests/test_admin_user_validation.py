import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.admin_routes import admin_router
from app.core.auth import require_admin
from app.db.session import get_db
from app.schemas.auth import AdminCreateUserRequest, AdminUpdateUserRequest


def test_admin_create_returns_readable_validation_errors_before_database_access():
    app = FastAPI()
    app.include_router(admin_router)
    app.dependency_overrides[require_admin] = lambda: {"role": "admin"}
    app.dependency_overrides[get_db] = lambda: None
    response = TestClient(app).post('/admin/users', json={
        'username': 'person@example.com', 'password': '123', 'email': 'invalid',
    })
    assert response.status_code == 422
    errors = {error['loc'][-1]: error for error in response.json()['detail']}
    assert errors['username']['type'] == 'string_pattern_mismatch'
    assert errors['username']['msg'] == '用户名须为 3–32 位小写字母、数字或下划线，且以字母开头；邮箱请填写到邮箱栏。'
    assert errors['password']['msg'] == '密码须为 6–128 个字符。'
    assert errors['email']['msg'] == '请输入有效的邮箱地址。'


@pytest.mark.parametrize('username', ['a', 'ab', 'a' * 33, 'A_1', '1user', '_user', '中文', 'with space', 'user@example.com'])
def test_username_constraints_remain_enforced(username):
    with pytest.raises(ValidationError, match='用户名须为'):
        AdminCreateUserRequest(username=username, password='123456')


@pytest.mark.parametrize('username', ['abc', 'a_1', 'a' * 32])
def test_valid_admin_create_boundaries_and_optional_email(username):
    user = AdminCreateUserRequest(username=username, password='p' * 128)
    assert user.username == username
    assert user.email is None
    assert AdminUpdateUserRequest(email=None).password is None


def test_admin_update_uses_same_readable_validation():
    with pytest.raises(ValidationError, match='请输入有效的邮箱地址'):
        AdminUpdateUserRequest(email='invalid')
    with pytest.raises(ValidationError, match='密码须为'):
        AdminUpdateUserRequest(password='123')


def test_admin_cannot_create_reserved_gallery_route_name():
    with pytest.raises(ValidationError, match='系统保留名称'):
        AdminCreateUserRequest(username='public', password='123456')
