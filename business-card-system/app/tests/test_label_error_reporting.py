"""下書きが作れなかったときの伝え方（poc/label.py）。

実テストで、画面にこれだけが出た。

    OCRの結果を取得できませんでした。空欄から入力してください。

これは画面側が**JSONとして読めなかった**ときの文言で、原因を何も含まない。
サーバー側で例外が出ると FastAPI は本文なしの 500 を返し、画面はそれを
JSONとして読もうとして失敗する。結果、何が起きたのか分からないまま
報告の往復になった。

理由は必ず画面に出す。そのために、この入口からは例外を出さない。
最後の受け皿は、原因になりうるものに頼らずに組み立てる。

あわせて全文をファイルへ残す。コンソールは流れて消えるうえ、閉じると
何も残らない。Windows の日本語環境では画面の文字コードが cp932 で、
書けない文字があると `print` 自体が例外を出すため、記録は UTF-8 の
バイトで書く。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))
sys.path.insert(0, str(APP))

import poc.label as label  # noqa: E402


@pytest.fixture
def cards(tmp_path: Path) -> Path:
    for name in ("card0.png", "card1.png"):
        Image.new("RGB", (1050, 640), "white").save(tmp_path / name)
    return tmp_path


@pytest.fixture(autouse=True)
def log_to_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """記録先を移す（リポジトリの中に書かないこと）。"""
    path = tmp_path / "ラベル入力ログ.txt"
    monkeypatch.setattr(label, "LOG_PATH", path)
    return path


def client(cards: Path) -> TestClient:
    return TestClient(label.build_app(cards, prefill=True), raise_server_exceptions=False)


class TestTheReasonReachesTheScreen:
    def test_a_working_card_still_gives_a_draft(self, cards: Path):
        got = client(cards).get("/api/label/card0.png").json()

        assert got["kind"] == "draft"
        assert got["values"]["last_name"]

    def test_a_failing_child_is_explained(self, cards: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(label, "run_in_child", _always_fails)

        got = client(cards).get("/api/label/card0.png").json()

        assert got["kind"] == "error"
        assert "わざと失敗" in got["source"]

    def test_an_unexpected_failure_is_still_json(self, cards: Path, monkeypatch: pytest.MonkeyPatch):
        """どこで落ちても本文なしの500にしないこと。ここが今回の不具合。"""
        monkeypatch.setattr(label, "FIELD_KEYS", None)

        response = client(cards).get("/api/label/card0.png")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")

    def test_an_unexpected_failure_names_the_error(self, cards: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(label, "FIELD_KEYS", None)

        got = client(cards).get("/api/label/card0.png").json()

        assert "TypeError" in got["source"]

    def test_the_last_resort_does_not_use_what_may_have_broken(
        self, cards: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """受け皿が原因に頼っていると、受け皿ごと落ちる（実際に落ちた）。"""
        monkeypatch.setattr(label, "FIELD_KEYS", None)

        got = client(cards).get("/api/label/card0.png").json()

        assert got["values"] == {}


class TestTheFullReasonIsKept:
    def test_a_failure_is_written_to_the_log(
        self, cards: Path, log_to_tmp: Path, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(label, "run_in_child", _always_fails)

        client(cards).get("/api/label/card0.png")

        assert "わざと失敗" in log_to_tmp.read_text(encoding="utf-8")

    def test_the_log_holds_the_whole_traceback(
        self, cards: Path, log_to_tmp: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """1行の要約では、どこで落ちたか分からない。"""
        monkeypatch.setattr(label, "run_in_child", _always_fails)

        client(cards).get("/api/label/card0.png")

        assert "Traceback" in log_to_tmp.read_text(encoding="utf-8")

    def test_writing_the_log_never_raises(self, log_to_tmp: Path, monkeypatch: pytest.MonkeyPatch):
        """記録できなくても本筋は止めない（書けない場所を指していても）。"""
        monkeypatch.setattr(label, "LOG_PATH", log_to_tmp / "つくれない" / "log.txt")

        label._log_failure("試し")  # 例外を出さなければよい


class TestTheVersionShownIsTheOneRunning:
    """版はサーバーが動かしているコードのもの。ディスクの版ではない。

    取得（git pull）はサーバーを立てたまま行えるため、ディスクだけが新しく
    なることがある。要求のたびにディスクを見ていたので、画面には新しい版が
    出るのに動いているのは古いコード、という状態を見分けられなかった。
    """

    def test_the_running_version_is_fixed_at_start(self):
        assert label._version() == label._RUNNING_VERSION

    def test_a_newer_disk_version_is_pointed_out(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(label, "_disk_version", lambda: "あたらしい版")

        shown = label._version()

        assert "あたらしい版" in shown
        assert "開き直して" in shown


def _always_fails(args: list[str]) -> dict:
    raise RuntimeError("わざと失敗 ソ")
