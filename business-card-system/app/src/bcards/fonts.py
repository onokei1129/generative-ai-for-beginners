"""日本語フォントの場所を環境ごとに解決する。

PoC のサンプル生成（`poc/samples.py`）やデモデータ作成（`seed.py`）で
名刺の画像を描くために使う。アプリ本体の動作には不要。

フォントのパスを決め打ちにすると、別のOSで
`OSError: cannot open resource` になる。実際に存在するものを探して使う。
"""

from __future__ import annotations

import sys
from functools import lru_cache
from glob import glob
from pathlib import Path

# 上から順に探す。同じOSでは同じフォントが選ばれるので、
# PoC の測定値が環境によってぶれることはない。
JAPANESE_CANDIDATES: tuple[str, ...] = (
    # Linux（この順で Debian/Ubuntu 系 → Noto → IPA → VL）
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/ipafont-gothic/ipag.ttf",
    "/usr/share/fonts/truetype/vlgothic/VL-Gothic-Regular.ttf",
    # Windows
    r"C:\Windows\Fonts\meiryo.ttc",
    r"C:\Windows\Fonts\YuGothM.ttc",
    r"C:\Windows\Fonts\YuGothR.ttc",
    r"C:\Windows\Fonts\msgothic.ttc",
    r"C:\Windows\Fonts\msmincho.ttc",
    # macOS
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
    "/System/Library/Fonts/Hiragino Sans GB.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
)

LATIN_CANDIDATES: tuple[str, ...] = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\segoeui.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
)

# 見つからなかった場合に探す場所（配布ごとにパスが違うため）
JAPANESE_GLOBS: tuple[str, ...] = (
    "/usr/share/fonts/**/NotoSansCJK*.ttc",
    "/usr/share/fonts/**/NotoSansJP*.otf",
    "/usr/share/fonts/**/*[Gg]othic*.tt[fc]",
    r"C:\Windows\Fonts\*[Gg]othic*.tt[fc]",
)


def _first_existing(candidates: tuple[str, ...]) -> str | None:
    for path in candidates:
        if Path(path).is_file():
            return path
    return None


@lru_cache(maxsize=1)
def japanese_font_path() -> str:
    """日本語を描けるフォントのパス。見つからなければ RuntimeError。"""
    found = _first_existing(JAPANESE_CANDIDATES)
    if found:
        return found

    for pattern in JAPANESE_GLOBS:
        matches = sorted(glob(pattern, recursive=True))
        if matches:
            return matches[0]

    raise RuntimeError(_missing_message())


@lru_cache(maxsize=1)
def latin_font_path() -> str:
    """英数字用のフォント。無ければ日本語フォントで代用する。"""
    return _first_existing(LATIN_CANDIDATES) or japanese_font_path()


def _missing_message() -> str:
    if sys.platform == "win32":
        how = (
            "  Windows には通常メイリオ（meiryo.ttc）が入っています。\n"
            "  設定 → 個人用設定 → フォント から日本語フォントを追加してください。"
        )
    elif sys.platform == "darwin":
        how = "  macOS には通常ヒラギノが入っています。フォントブックを確認してください。"
    else:
        how = (
            "  次のいずれかでインストールしてください。\n"
            "    sudo apt-get install -y fonts-noto-cjk\n"
            "    sudo apt-get install -y fonts-ipafont-gothic"
        )
    return (
        "日本語を描けるフォントが見つかりませんでした。\n"
        "サンプル画像の生成にはフォントが必要です。\n" + how
    )


def load(size: int, latin: bool = False):
    """Pillow のフォントオブジェクトを返す。"""
    from PIL import ImageFont

    path = latin_font_path() if latin else japanese_font_path()
    return ImageFont.truetype(path, size)
