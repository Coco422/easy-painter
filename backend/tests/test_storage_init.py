from types import SimpleNamespace
from unittest.mock import Mock, call

import pytest
from minio.error import S3Error

from app.services import storage_init


def s3_error(code):
    return S3Error(code, code, "test-bucket", "request", "host", None)


@pytest.fixture
def client(monkeypatch):
    client = Mock()
    client.bucket_exists.return_value = False
    storage = SimpleNamespace(client=client, bucket="media", reference_bucket="references")
    monkeypatch.setattr(storage_init, "MinioStorageService", lambda: storage)
    return client


def test_creates_both_private_buckets(client):
    storage_init.initialize_storage()
    assert client.make_bucket.call_args_list == [call("media"), call("references")]
    assert client.delete_bucket_policy.call_args_list == [call("media"), call("references")]


def test_existing_buckets_are_kept_and_anonymous_policies_removed(client):
    client.bucket_exists.return_value = True
    storage_init.initialize_storage()
    client.make_bucket.assert_not_called()
    assert client.delete_bucket_policy.call_args_list == [call("media"), call("references")]


def test_missing_policy_is_already_private(client):
    client.delete_bucket_policy.side_effect = s3_error("NoSuchBucketPolicy")
    storage_init.initialize_storage()
    assert client.delete_bucket_policy.call_count == 2


def test_concurrent_bucket_creation_still_removes_public_policy(client):
    client.make_bucket.side_effect = s3_error("BucketAlreadyOwnedByYou")
    storage_init.initialize_storage()
    assert client.delete_bucket_policy.call_count == 2


@pytest.mark.parametrize("operation", ["bucket_exists", "make_bucket", "delete_bucket_policy"])
def test_access_denied_fails_initialization_instead_of_starting_app(client, operation):
    getattr(client, operation).side_effect = s3_error("AccessDenied")
    with pytest.raises(S3Error, match="AccessDenied"):
        storage_init.initialize_storage()


def test_shared_bucket_is_initialized_once(client, monkeypatch):
    monkeypatch.setattr(storage_init, "MinioStorageService", lambda: SimpleNamespace(
        client=client, bucket="media", reference_bucket="media",
    ))
    storage_init.initialize_storage()
    client.make_bucket.assert_called_once_with("media")
    client.delete_bucket_policy.assert_called_once_with("media")
