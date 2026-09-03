"""ストレージ実装の切り替えテスト。

本番でS3へ差し替えたときに、アプリ側のコードを変えずに同じ振る舞いをすることを確認する。
S3はモック（moto）で検証しており、実際のAWSには接続しない。
"""

from __future__ import annotations

import pytest

from bcards.services import storage


@pytest.fixture(autouse=True)
def restore_backend():
    yield
    storage.set_backend(None)


def _round_trip(backend) -> None:
    storage.set_backend(backend)
    payload = b"business card image bytes"

    key = storage.put_bytes(payload, suffix=".jpg", prefix="cards/original")
    assert key.startswith("cards/original/")
    assert storage.exists(key)
    assert storage.get_bytes(key) == payload

    # 同じ内容は同じキーになる（二重保存しない）
    assert storage.put_bytes(payload, suffix=".jpg", prefix="cards/original") == key
    assert storage.total_bytes() >= len(payload)

    storage.delete(key)
    assert not storage.exists(key)


def test_local_backend_round_trip(tmp_path):
    _round_trip(storage.LocalStorageBackend(root=tmp_path))


def test_s3_backend_round_trip():
    boto3 = pytest.importorskip("boto3")
    moto = pytest.importorskip("moto")

    with moto.mock_aws():
        boto3.client("s3", region_name="ap-northeast-1").create_bucket(
            Bucket="bcards-test",
            CreateBucketConfiguration={"LocationConstraint": "ap-northeast-1"},
        )
        backend = storage.S3StorageBackend(bucket="bcards-test", key_prefix="business-cards")
        _round_trip(backend)


def test_s3_backend_applies_key_prefix():
    """バケットを他システムと共用しても衝突しないよう、接頭辞を付ける。"""
    boto3 = pytest.importorskip("boto3")
    moto = pytest.importorskip("moto")

    with moto.mock_aws():
        client = boto3.client("s3", region_name="ap-northeast-1")
        client.create_bucket(
            Bucket="bcards-test",
            CreateBucketConfiguration={"LocationConstraint": "ap-northeast-1"},
        )
        backend = storage.S3StorageBackend(bucket="bcards-test", key_prefix="business-cards")
        storage.set_backend(backend)
        key = storage.put_bytes(b"x", suffix=".jpg", prefix="cards/display")

        listed = [obj["Key"] for obj in client.list_objects_v2(Bucket="bcards-test")["Contents"]]
        assert listed == [f"business-cards/{key}"]


def test_s3_backend_has_no_free_space_concept():
    boto3 = pytest.importorskip("boto3")
    moto = pytest.importorskip("moto")

    with moto.mock_aws():
        boto3.client("s3", region_name="ap-northeast-1").create_bucket(
            Bucket="bcards-test",
            CreateBucketConfiguration={"LocationConstraint": "ap-northeast-1"},
        )
        backend = storage.S3StorageBackend(bucket="bcards-test")
        assert backend.free_space_bytes() is None


def test_unknown_backend_is_rejected(monkeypatch):
    from bcards.config import settings

    monkeypatch.setattr(settings, "storage_backend", "dropbox")
    storage.set_backend(None)
    with pytest.raises(ValueError):
        storage.get_backend()
