"""バックアップ・復元スクリプトの回帰テスト。

第1回の復元訓練（../restore-drill-2026-07.md）で、
取得元と復元先でディレクトリ名が違うと画像が別の場所へ展開される不具合を検出した。
tar の固め方・展開の仕方だけを切り出して検証する（DB部分は pg_dump に依存するため対象外）。
"""

from __future__ import annotations

import functools
import os
import shutil
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
def test_scripts_are_executable(script):
    """実行権限が付いた状態でリポジトリに入っているか。

    ファイルシステムの権限ではなく **git が記録しているモード** を見る。
    NTFS には実行権限の概念が無いため、Windows で開発している場合に
    ローカルのモードを見ると必ず失敗してしまう。
    実際に問題になるのは「Linuxサーバーへ配置したときに実行できるか」であり、
    それを決めるのは git 側のモード（100755）である。
    """
    path = OPS / script
    assert path.exists(), f"{script} がありません"

    try:
        # ファイル名だけを渡す（Windows の区切り文字に左右されないように）
        result = subprocess.run(
            ["git", "ls-files", "-s", "--", script],
            capture_output=True, text=True, check=True, cwd=OPS,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        pytest.skip(f"git で確認できないため省略します: {exc}")

    if not result.stdout.strip():
        pytest.skip(f"{script} は git の管理下にありません")

    mode = result.stdout.split()[0]
    assert mode == "100755", (
        f"{script} に実行権限がありません（git のモード: {mode}）。"
        f" `git update-index --chmod=+x app/ops/{script}` で付けてください。"
    )


@functools.lru_cache(maxsize=1)
def working_bash() -> str | None:
    """実際に動く bash の場所を返す。無ければ None。

    Windows では `bash` を探すと `C:\\Windows\\System32\\bash.exe`（WSLの起動用）が
    先に見つかることが多い。WSLが入っていないとこれは起動に失敗するため、
    「見つかったか」ではなく「動くか」で判定する。
    Git for Windows の bash も候補に入れる。
    """
    candidates = [shutil.which("bash")]
    if os.name == "nt":
        candidates += [
            r"C:\Program Files\Git\bin\bash.exe",
            r"C:\Program Files (x86)\Git\bin\bash.exe",
        ]

    for candidate in candidates:
        if not candidate or not Path(candidate).exists():
            continue
        try:
            # 中身の無いスクリプトで動作確認する。ここが通らない bash は使えない
            probe = subprocess.run(
                [candidate, "-n", "-c", ":"], capture_output=True, timeout=30
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if probe.returncode == 0:
            return candidate
    return None


@pytest.mark.parametrize("script", ["backup.sh", "restore.sh"])
def test_scripts_have_no_syntax_error(script):
    """構文エラーがあると、障害対応の最中に初めて気づくことになる。"""
    bash = working_bash()
    if bash is None:
        pytest.skip("動作する bash が無いため省略します（Windows で WSL 未導入など）")

    result = subprocess.run(
        [bash, "-n", str(OPS / script)], capture_output=True, text=True, errors="replace"
    )
    assert result.returncode == 0, f"{script} に構文エラーがあります:\n{result.stderr}"
