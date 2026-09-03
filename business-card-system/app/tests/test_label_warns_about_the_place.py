"""置き場所の警告が、気づける場所に出ること。

実テストでサーバーが跡形もなく消え続けた原因は、`.venv` ごと Dropbox の
中に置かれていたこと（`poc/sync_folder.py` の冒頭に理屈を書いた）。

**この原因は、記録を送ってもらっても分からない。** 記録に何も残らない
ことこそが症状だからである。したがって、こちらから先に伝えるしかない。
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from poc import label


class TestTheScreenIsTold:
    def test_the_file_list_carries_the_warning(self, tmp_path: Path, monkeypatch):
        """画面が受け取れること。中身の有無は置き場所しだい。"""
        (tmp_path / "a.png").write_bytes(b"x")
        app = label.build_app(tmp_path, prefill=False)

        with TestClient(app) as client:
            body = client.get("/api/files").json()

        assert "sync_warning" in body, "置き場所の警告を画面へ渡していない"

    def test_the_warning_is_filled_in_when_inside_a_sync_folder(
        self, tmp_path: Path, monkeypatch
    ):
        root = tmp_path / "Dropbox"
        (root / "app" / ".venv").mkdir(parents=True)
        (root / ".dropbox").write_text("", encoding="utf-8")
        monkeypatch.setattr(
            label.sys, "executable", str(root / "app" / ".venv" / "python")
        )

        pictures = tmp_path / "画像"
        pictures.mkdir()
        (pictures / "a.png").write_bytes(b"x")
        app = label.build_app(pictures, prefill=False)

        with TestClient(app) as client:
            body = client.get("/api/files").json()

        assert "Dropbox" in body["sync_warning"]

    def test_the_died_notice_leads_with_it(self):
        """**消えたときの案内で、記録を送ってと頼む前に伝える。**

        記録には何も残らないのだから、記録を頼むだけでは前に進まない。
        """
        source = Path(label.__file__).read_text(encoding="utf-8")
        start = source.index("function serverDiedNotice(")
        body = source[start : source.index("\n}", start)]

        assert "syncWarning" in body, "消えたときの案内に置き場所の話が無い"
        assert body.index("syncWarning") < body.index("state.logs"), (
            "記録を頼むより先に、分かっている原因を伝えること"
        )


class TestTheBlackWindowIsTold:
    def test_the_warning_comes_before_the_card_count(self):
        """**200枚入力したあとに気づくのでは遅い。**"""
        source = Path(label.__file__).read_text(encoding="utf-8")
        start = source.index("def main(")

        assert source.index("warning_for_this_run()", start) < source.index(
            'print(f"対象: {directory}")', start
        )


class TestThePageIsValidJavaScript:
    """画面の JavaScript は Python の文字列の中にある。**二重に解釈される。**

    `PAGE` は素の三重引用符なので、`\\t` や `\\n` と書くと Python が本物の
    タブや改行に変えてしまう。JavaScript の正規表現に生の改行が入ると
    構文エラーになり、**画面全体が動かなくなる**。実際に一度そう書いた。

    ファイルには `\\\\s` と書き、PAGE の中身が `\\s` になるのが正しい。
    """

    def test_no_regex_literal_contains_a_raw_newline(self):
        for number, line in enumerate(label.PAGE.splitlines(), 1):
            if ".replace(/" in line or ".match(/" in line:
                assert "\t" not in line, f"{number}行目の正規表現に生のタブ"

    def test_the_whitespace_regex_survives_both_layers(self):
        line = next(
            l for l in label.PAGE.splitlines() if "syncWarning.replace" in l
        )
        assert "/\\s+/g" in line, f"JavaScript に渡る字面が壊れている: {line!r}"
