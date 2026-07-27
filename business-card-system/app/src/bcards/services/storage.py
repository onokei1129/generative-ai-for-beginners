"""オブジェクトストレージ層。

ローカルファイルシステムに保存する実装。本番では S3 / Blob Storage / Cloud Storage に
置き換える（このモジュールの関数シグネチャを保てばアプリ側の変更は不要）。
"""

from __future__ import annotations

import hashlib
import shutil
from datetime import datetime
from pathlib import Path

from ..config import settings


def _path_for(key: str) -> Path:
    path = (settings.storage_dir / key).resolve()
    root = settings.storage_dir.resolve()
    if not str(path).startswith(str(root)):
        raise ValueError("不正なストレージキーです。")
    return path


def put_bytes(data: bytes, *, suffix: str, prefix: str = "cards") -> str:
    digest = hashlib.sha256(data).hexdigest()
    today = datetime.now().strftime("%Y/%m/%d")
    key = f"{prefix}/{today}/{digest[:32]}{suffix}"
    path = _path_for(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_bytes(data)
    return key


def get_bytes(key: str) -> bytes:
    return _path_for(key).read_bytes()


def get_path(key: str) -> Path:
    return _path_for(key)


def exists(key: str) -> bool:
    return _path_for(key).exists()


def delete(key: str) -> None:
    path = _path_for(key)
    if path.exists():
        path.unlink()


def checksum(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def total_bytes() -> int:
    total = 0
    for path in settings.storage_dir.rglob("*"):
        if path.is_file():
            total += path.stat().st_size
    return total


def free_space_bytes() -> int:
    usage = shutil.disk_usage(settings.storage_dir)
    return usage.free
