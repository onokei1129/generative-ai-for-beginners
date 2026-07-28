"""OCR精度の計測（PoC）用のモジュール群。

`poc.*` を import した時点でアプリ本体（`src/bcards`）を読めるようにしておく。
各スクリプトが個別に sys.path を書き換えると、書き忘れたものだけ
`ModuleNotFoundError: No module named 'bcards'` になるため、ここでまとめて行う。
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = str(Path(__file__).resolve().parents[1] / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
