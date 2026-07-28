"""オブジェクトストレージ層。

BCARDS_STORAGE_BACKEND で実装を切り替える。

    local : ローカルファイルシステム（開発・単一サーバー用。既定）
    s3    : Amazon S3 および S3 互換ストレージ（MinIO 等）

Azure Blob / Google Cloud Storage を使う場合も、StorageBackend を実装して
_BACKENDS に登録すれば、アプリ側の呼び出しは変更しなくてよい。
"""

from __future__ import annotations

import hashlib
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Protocol

from ..config import settings


class StorageBackend(Protocol):
    def put_bytes(self, data: bytes, *, suffix: str, prefix: str) -> str: ...

    def get_bytes(self, key: str) -> bytes: ...

    def exists(self, key: str) -> bool: ...

    def delete(self, key: str) -> None: ...

    def total_bytes(self) -> int: ...

    def free_space_bytes(self) -> int | None: ...


def build_key(data: bytes, *, suffix: str, prefix: str) -> str:
    """内容ハッシュに基づくキー。同じ画像を二重に保存しない。"""
    digest = hashlib.sha256(data).hexdigest()
    today = datetime.now().strftime("%Y/%m/%d")
    return f"{prefix}/{today}/{digest[:32]}{suffix}"


class LocalStorageBackend:
    """ローカルファイルシステム。"""

    name = "local"

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or settings.storage_dir).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path_for(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not str(path).startswith(str(self.root)):
            raise ValueError("不正なストレージキーです。")
        return path

    def put_bytes(self, data: bytes, *, suffix: str, prefix: str) -> str:
        key = build_key(data, suffix=suffix, prefix=prefix)
        path = self._path_for(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(data)
        return key

    def get_bytes(self, key: str) -> bytes:
        return self._path_for(key).read_bytes()

    def get_path(self, key: str) -> Path:
        return self._path_for(key)

    def exists(self, key: str) -> bool:
        return self._path_for(key).exists()

    def delete(self, key: str) -> None:
        path = self._path_for(key)
        if path.exists():
            path.unlink()

    def total_bytes(self) -> int:
        return sum(path.stat().st_size for path in self.root.rglob("*") if path.is_file())

    def free_space_bytes(self) -> int | None:
        return shutil.disk_usage(self.root).free


class S3StorageBackend:
    """Amazon S3 / S3互換ストレージ。

    認証情報は boto3 の標準的な解決順（環境変数・インスタンスロール等）に従う。
    アプリにアクセスキーを直接持たせず、IAMロールを使う運用を推奨する。
    """

    name = "s3"

    def __init__(self, bucket: str | None = None, key_prefix: str | None = None) -> None:
        import boto3

        self.bucket = bucket or settings.s3_bucket
        if not self.bucket:
            raise RuntimeError("BCARDS_S3_BUCKET が設定されていません。")
        self.key_prefix = (key_prefix if key_prefix is not None else settings.s3_key_prefix).strip("/")
        client_args: dict = {}
        if settings.s3_endpoint_url:  # MinIO 等のS3互換ストレージ
            client_args["endpoint_url"] = settings.s3_endpoint_url
        if settings.s3_region:
            client_args["region_name"] = settings.s3_region
        self.client = boto3.client("s3", **client_args)

    def _full_key(self, key: str) -> str:
        return f"{self.key_prefix}/{key}" if self.key_prefix else key

    def put_bytes(self, data: bytes, *, suffix: str, prefix: str) -> str:
        key = build_key(data, suffix=suffix, prefix=prefix)
        self.client.put_object(
            Bucket=self.bucket,
            Key=self._full_key(key),
            Body=data,
            **({"ServerSideEncryption": settings.s3_sse} if settings.s3_sse else {}),
        )
        return key

    def get_bytes(self, key: str) -> bytes:
        response = self.client.get_object(Bucket=self.bucket, Key=self._full_key(key))
        return response["Body"].read()

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError

        try:
            self.client.head_object(Bucket=self.bucket, Key=self._full_key(key))
            return True
        except ClientError:
            return False

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=self._full_key(key))

    def total_bytes(self) -> int:
        paginator = self.client.get_paginator("list_objects_v2")
        total = 0
        for page in paginator.paginate(Bucket=self.bucket, Prefix=self.key_prefix or ""):
            for obj in page.get("Contents", []):
                total += obj["Size"]
        return total

    def free_space_bytes(self) -> int | None:
        return None  # オブジェクトストレージに空き容量の概念はない


_BACKENDS = {"local": LocalStorageBackend, "s3": S3StorageBackend}

_backend: StorageBackend | None = None


def get_backend() -> StorageBackend:
    global _backend
    if _backend is None:
        factory = _BACKENDS.get((settings.storage_backend or "local").lower())
        if factory is None:
            raise ValueError(f"未知のストレージ実装です: {settings.storage_backend}")
        _backend = factory()
    return _backend


def set_backend(backend: StorageBackend | None) -> None:
    """テストや切り替え用。None を渡すと設定から作り直す。"""
    global _backend
    _backend = backend
    invalidate_usage_cache()


# --------------------------------------------------------------------------
# アプリから使う関数（実装の違いを吸収する）
# --------------------------------------------------------------------------


def put_bytes(data: bytes, *, suffix: str, prefix: str = "cards") -> str:
    return get_backend().put_bytes(data, suffix=suffix, prefix=prefix)


def get_bytes(key: str) -> bytes:
    return get_backend().get_bytes(key)


def get_path(key: str) -> Path:
    """ローカル保存時のみ利用できる。オブジェクトストレージでは使わない。"""
    backend = get_backend()
    if not isinstance(backend, LocalStorageBackend):
        raise NotImplementedError("このストレージ実装にはローカルパスがありません。")
    return backend.get_path(key)


def exists(key: str) -> bool:
    return get_backend().exists(key)


def delete(key: str) -> None:
    get_backend().delete(key)


def checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------
# 使用量の集計（キャッシュつき）
# --------------------------------------------------------------------------
#
# 使用量はホーム画面と管理画面で毎回参照するが、集計そのものは重い。
# ローカル保存ではディレクトリ全体を走査し（画像3万件で実測 490ms）、
# S3 ではバケット全体を ListObjectsV2 でページングするため、
# 画面を開くたびに API 呼び出しが発生してしまう。
#
# この値は容量アラートの判定に使うもので、秒単位の正確さは要らない。
# 短時間キャッシュして、画面表示のたびに集計しないようにする。

_usage_cache: tuple[float, int] | None = None


def invalidate_usage_cache() -> None:
    global _usage_cache
    _usage_cache = None


def total_bytes(*, fresh: bool = False) -> int:
    """保存されているオブジェクトの合計サイズ。

    fresh=True で必ず集計し直す（管理画面の「最新に更新」用）。
    """
    global _usage_cache
    ttl = settings.storage_usage_cache_seconds
    if not fresh and ttl > 0 and _usage_cache is not None:
        cached_at, value = _usage_cache
        if time.monotonic() - cached_at < ttl:
            return value

    value = get_backend().total_bytes()
    _usage_cache = (time.monotonic(), value)
    return value


def usage_measured_at() -> float | None:
    """使用量を最後に集計した時刻（time.monotonic 基準）。未集計なら None。"""
    return _usage_cache[0] if _usage_cache else None


def free_space_bytes() -> int | None:
    return get_backend().free_space_bytes()
