"""バックアップ・復元スクリプトの回帰テスト。

第1回の復元訓練（../restore-drill-2026-07.md）で、
取得元と復元先でディレクトリ名が違うと画像が別の場所へ展開される不具合を検出した。
tar の固め方・展開の仕方だけを切り出して検証する（DB部分は pg_dump に依存するため対象外）。
"""

from __future__ import annotations

import subprocess
import tarfile
from pathlib import Path

import pytest

OPS = Path(__file__).resolve().parents[1] / "ops"


def _make_objects(root: Path) -> None:
    (root / "cards" / "display").mkdir(parents=True)
    (root / "cards" / "display" / "a.jpg").write_bytes(b"image-a")
    (root / "uploads").mkdir()
    (root / "uploads" / "b.jpg").write_bytes(b"image-b")


def _archive(source: Path, dest: Path) -> None:
    """ops/backup.sh と同じ固め方。"""
    subprocess.run(["tar", "-C", str(source), "-czf", str(dest), "."], check=True)


def test_archive_does_not_embed_the_directory_name(tmp_path):
    source = tmp_path / "objects"
    source.mkdir()
    _make_objects(source)
    archive = tmp_path / "objects.tar.gz"
    _archive(source, archive)

    with tarfile.open(archive) as tar:
        names = tar.getnames()
    # "objects/..." を含んでいると、復元先のディレクトリ名が違うときに壊れる
    assert not any(name.startswith("objects/") for name in names)
    assert "./cards/display/a.jpg" in names


def test_restore_extracts_into_the_configured_directory(tmp_path):
    source = tmp_path / "objects"
    source.mkdir()
    _make_objects(source)
    archive = tmp_path / "objects.tar.gz"
    _archive(source, archive)

    # 復元先のディレクトリ名は取得元と違う
    dest = tmp_path / "restored-objects"
    dest.mkdir()
    subprocess.run(["tar", "-C", str(dest), "-xzf", str(archive)], check=True)

    assert (dest / "cards" / "display" / "a.jpg").read_bytes() == b"image-a"
    assert (dest / "uploads" / "b.jpg").read_bytes() == b"image-b"
    # 取得元のディレクトリ名で余計な階層が作られていないこと
    assert not (dest / "objects").exists()


def test_restore_handles_the_old_archive_format(tmp_path):
    """旧書式（objects/ を含む）でも --strip-components=1 で正しく戻せる。"""
    source = tmp_path / "objects"
    source.mkdir()
    _make_objects(source)
    archive = tmp_path / "old.tar.gz"
    subprocess.run(["tar", "-C", str(tmp_path), "-czf", str(archive), "objects"], check=True)

    with tarfile.open(archive) as tar:
        first = tar.getnames()[0]
    assert first.startswith("objects")  # 旧書式の判定条件

    dest = tmp_path / "restored"
    dest.mkdir()
    subprocess.run(
        ["tar", "-C", str(dest), "-xzf", str(archive), "--strip-components=1"], check=True
    )
    assert (dest / "cards" / "display" / "a.jpg").read_bytes() == b"image-a"


@pytest.mark.parametrize("script", ["backup.sh", "restore.sh"])
def test_scripts_are_executable_and_valid_bash(script):
    path = OPS / script
    assert path.exists(), f"{script} がありません"
    assert path.stat().st_mode & 0o111, f"{script} に実行権限がありません"
    # 構文エラーがあると、障害対応の最中に初めて気づくことになる
    subprocess.run(["bash", "-n", str(path)], check=True)
