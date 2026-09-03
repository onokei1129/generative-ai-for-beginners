"""サーバーが落ちたとき、記録の在り処を画面に出す（poc/label.py）。

これまでの案内はこうだった。

    サーバーが応答していません。「ラベル付けを始める」の黒い画面を閉じて、
    もう一度開いてください。（黒い画面の最後の行が原因の手がかりです）

**閉じれば手がかりは消える。** 同じ一文で「手がかりは黒い画面にある」と
言いながら「閉じてください」と案内していた。実テストでは実際に、落ちた回の
記録が3度お願いしても届かなかった。

記録は2つのファイルにも残る（`ラベル入力ログ.txt` と `落ちた記録.txt`）。
こちらは黒い画面を閉じても残るので、在り処を画面に出す。

在り処はサーバーが**生きているうちに**受け取っておくこと。落ちてから
訊きに行っても繋がらない。実テスト24枚目（Donuts）の画面がその状態で、

    書き出せませんでした: TypeError: Failed to fetch

と出ていた。この文言もサーバーが落ちている印なので、そのまま出さない。
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))
sys.path.insert(0, str(APP))

import poc.label as label  # noqa: E402

NOTICE = "serverDiedNotice"


class TestTheServerHandsOverThePaths:
    def test_api_files_carries_them(self, tmp_path: Path):
        Image.new("RGB", (300, 190), "white").save(tmp_path / "a.png")

        with TestClient(label.build_app(tmp_path, False)) as client:
            body = client.get("/api/files").json()

        assert "logs" in body, "記録の在り処を渡していない"
        assert str(label.LOG_PATH) in body["logs"]
        assert str(label.CRASH_PATH) in body["logs"]


class TestThePageKeepsThemForLater:
    def test_boot_stores_them(self):
        """落ちる前に受け取っておく。落ちてからでは訊きに行けない。"""
        start = label.PAGE.index("async function boot()")
        body = label.PAGE[start : label.PAGE.index("\nfunction ", start)]

        assert "meta.logs" in body, "起動時に記録の在り処を控えていない"

    def test_the_notice_is_built_from_what_was_stored(self):
        """案内は控えた在り処から組む。落ちたあとに取りに行かない。"""
        start = label.PAGE.index(f"function {NOTICE}(")
        body = label.PAGE[start : label.PAGE.index("\n}", start)]

        assert "state.logs" in body, "記録の在り処を出していない"
        assert "fetch" not in body, "落ちたあとに訊きに行っている"


class TestEveryPlaceUsesTheSameNotice:
    """「応答していません」を出す場所を、書き分けたまま残さない。"""

    def test_there_is_only_one_wording(self):
        assert label.PAGE.count("サーバーが応答していません") == 1, (
            "案内が複数の場所に書き分けられている"
        )

    def test_all_three_places_call_it(self):
        """画像・下書き・書き出しの3か所。定義そのものを数に入れない。"""
        assert label.PAGE.count(NOTICE) == 1 + 3

    def test_the_export_failure_does_not_show_the_raw_error(self):
        """`TypeError: Failed to fetch` をそのまま出さない。"""
        start = label.PAGE.index("'inspect'")
        body = label.PAGE[start : label.PAGE.index("\n};", start)]

        assert NOTICE in body, "書き出しの失敗でサーバーの死を見ていない"
        assert "serverIsAlive" in body, "この1枚の問題かどうかを分けていない"

    def test_it_no_longer_only_points_at_the_window(self):
        """黒い画面だけを手がかりにしない（閉じれば消えるため）。

        なぜ止めたのかを書いた注釈は残す。数えるのは**画面に出る文**だけ。
        """
        shown = [
            line
            for line in label.PAGE.splitlines()
            if not line.lstrip().startswith("//")
        ]

        assert not [
            line for line in shown if "黒い画面の最後の行が原因の手がかりです" in line
        ]
