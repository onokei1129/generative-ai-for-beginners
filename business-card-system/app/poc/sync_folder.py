"""同期フォルダ（Dropbox など）の上で動いていないかを調べる。

## なぜこれが要るのか

実テストで、サーバーが**跡形もなく消える**事象が繰り返し起きた。

  - `落ちた記録.txt`（faulthandler）に何も残らない
  - `--- 終了 ---` も「サーバーが落ちました」も出ない
  - 落ちる場所は毎回ちがう。5秒で消える回もあれば10分もつ回もある
  - 直前に、使用メモリが**増えるのではなく減っていた**
    （107MB→88→72→49→37→23MB、子は10MB→4MB）

置き場所が `C:\\Users\\...\\Dropbox\\...` の中で、**`.venv` ごと同期
されていた**。

Python の実行ファイルも、拡張モジュール（`.pyd`）も、EasyOCR が使う
PyTorch の巨大なDLL群も、すべてファイルから**その都度読み込まれる**
（メモリ写像）。全部を最初にメモリへ載せるのではなく、必要になった
ページだけを、そのつどディスクから取り出す。

同期ソフトはその同じファイルを常時見張り、内容を読み、書き換え、
場合によっては「オンラインのみ」の見かけだけのファイルに置き換える。

使用メモリが減っていたのは、Windows がページを追い出していた跡である。
追い出されたページが再び要るとき、Windows は元のファイルから読み直す。
そのファイルが同期ソフトに掴まれていたり、実体が無くなっていると、
**読み直しに失敗する**（STATUS_IN_PAGE_ERROR / 0xC0000006）。

これは例外ではない。OS がその場でプロセスを消す。**Python の後始末も、
faulthandler も動かない**——それらもまた、動かすにはページが要るからだ。
記録が何も残らないのは、そのためである。

## 直し方

`.venv` と作業用のファイルを、同期フォルダの**外**に置く。
"""

from __future__ import annotations

import sys
from pathlib import Path

# 同期の目印。フォルダ名だけで決めない——`Dropbox` という名前の
# ただのフォルダを作っている人もいる。同期ソフトが置く印を優先する。
MARKERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Dropbox", (".dropbox", ".dropbox.cache")),
    ("OneDrive", (".849C9593-D756-4E56-8D6E-42412F2A707B",)),
    ("iCloud Drive", (".iCloud",)),
)

# 印が見つからないときに使う、フォルダ名での判定。
NAMES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Dropbox", ("dropbox",)),
    ("OneDrive", ("onedrive",)),
    ("iCloud Drive", ("iclouddrive", "icloud drive")),
    ("Google ドライブ", ("google drive", "googledrive", "my drive")),
)


def sync_folder_for(path: Path) -> tuple[str, Path] | None:
    """`path` が同期フォルダの中なら「（サービス名, 同期の根）」を返す。

    外なら `None`。判断がつかないときも `None`——**誤った警告は、
    本当の警告を読み飛ばさせる**。
    """
    try:
        here = Path(path).resolve()
    except OSError:
        return None

    for folder in (here, *here.parents):
        for service, marks in MARKERS:
            if any((folder / mark).exists() for mark in marks):
                return service, folder

    for folder in (here, *here.parents):
        lowered = folder.name.lower()
        for service, names in NAMES:
            # 完全一致で見る。`OneDrive - 会社名` のような形もあるので
            # そこだけ前方一致を許す。
            if lowered in names or any(
                lowered.startswith(name + " -") for name in names
            ):
                return service, folder

    return None


def warning_for_this_run() -> str:
    """いま動いている Python が同期フォルダの中なら、その説明を返す。

    外なら空文字。判定は**実行ファイルの位置**で行う——消える原因は
    `.venv` の中身が読み直せなくなることなので、見るべきはそこである。
    """
    found = sync_folder_for(Path(sys.executable))
    if found is None:
        return ""
    service, root = found
    return (
        f"【この置き場所では、サーバーが突然消えることがあります】\n"
        f"  いま {service} の中で動いています: {root}\n"
        f"\n"
        f"  Python 本体と部品（.venv）が同期の対象に入っています。\n"
        f"  同期ソフトがそれらのファイルを掴んでいる間に、Windows が\n"
        f"  読み直そうとして失敗すると、**記録を何も残さずに**プロセスが\n"
        f"  消えます。落ちる場所が毎回ちがうのはそのためです。\n"
        f"\n"
        f"  直すには、このアプリ一式を {service} の外へ移してください。\n"
        f"  例: C:\\名刺管理アプリケーション\n"
        f"  移したあとは .venv を作り直してください。"
    )
