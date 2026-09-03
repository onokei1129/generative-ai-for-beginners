"""動作確認（poc/doctor.py）が、部品を正しく試せていること。

doctor は部品ごとに**別のプロセス**で試す。異常終了（不正命令・DLLの
読み込み失敗）は例外ではなくプロセスごと落とすため、同じプロセスで
試すと診断そのものが道連れになるという理由による。

そのぶん、親が通したパスは子に引き継がれない。渡していなかったため、
アプリ側の2件は必ず

    ModuleNotFoundError: No module named 'bcards'

で落ちていた。**部品は動いているのに「動かない」と報告していた。**
診断の道具が嘘をつくと、そこから先の切り分けが全部むだになる。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))

from poc.doctor import CHECKS, OPTIONAL_CHECKS, child_env, run_check  # noqa: E402


class TestTheChildCanImportTheApp:
    def test_the_path_reaches_the_child(self):
        completed = subprocess.run(
            [sys.executable, "-c", "import bcards; print('ok')"],
            capture_output=True,
            text=True,
            env=child_env(),
            timeout=60,
        )

        assert completed.returncode == 0, completed.stderr

    def test_an_existing_pythonpath_is_kept(self, monkeypatch):
        monkeypatch.setenv("PYTHONPATH", "/somewhere/else")

        assert "/somewhere/else" in child_env()["PYTHONPATH"]

    def test_the_app_checks_actually_run(self):
        """これが落ちていたのが元の不具合。"""
        code = dict(CHECKS)["アプリの画像処理（取込と同じ経路）"]

        returncode, output = run_check(code)

        assert returncode == 0, output
        assert "ModuleNotFoundError" not in output


class TestAnOptionalPartDoesNotFailTheRun:
    def test_easyocr_is_marked_optional(self):
        """入っていなくても取込は動く。NGにすると本当の故障が埋もれる。"""
        assert any(name in OPTIONAL_CHECKS for name, _ in CHECKS)

    def test_every_optional_name_is_a_real_check(self):
        """名前を書き換えたときに、印だけ取り残されるのを防ぐ。"""
        names = {name for name, _ in CHECKS}

        assert OPTIONAL_CHECKS <= names
