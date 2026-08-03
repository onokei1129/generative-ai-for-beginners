"""どの部品が動かないのかを切り分ける。

    .venv/bin/python -m poc.doctor

「OCRを使えませんでした」のような一括りのエラーだけでは、原因が
tesseract なのか、画像処理なのか、PDFの読み込みなのかが分からない。
ここでは部品ごとに**別のプロセスで**試し、落ちた場所を特定する。

別プロセスにするのは、この種の異常終了（不正命令・DLLの読み込み失敗）が
例外ではなくプロセスごと落とすためで、同じプロセス内で試すと
診断そのものが道連れになって何も分からない。
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

# 終了コードの意味。Windows の異常終了は負の値で返る。
FATAL_CODES = {
    -1073741795: (
        "不正命令 (0xC000001D)",
        "このCPUに無い命令を使うようにビルドされた部品です。"
        "古いCPUで、AVX2 などを前提にしたパッケージを入れると起きます。",
    ),
    -1073741819: (
        "アクセス違反 (0xC0000005)",
        "部品の内部で異常終了しました。バージョンの組み合わせが原因のことが多いです。",
    ),
    -1073741515: (
        "DLLが見つからない (0xC0000135)",
        "必要なランタイム（Visual C++ 再頒布可能パッケージなど）が入っていません。",
    ),
}

CHECKS: list[tuple[str, str]] = [
    (
        "NumPy（数値計算）",
        """
        import numpy as np
        a = np.random.RandomState(0).rand(512, 512)
        print("ok", float((a @ a).sum() > 0))
        """,
    ),
    (
        "Pillow（画像の読み書き）",
        """
        from PIL import Image
        im = Image.new("RGB", (800, 500), "white")
        im.rotate(90, expand=True).resize((400, 250))
        print("ok")
        """,
    ),
    (
        "OpenCV（読み込みだけ）",
        """
        import cv2
        print("ok", cv2.__version__)
        """,
    ),
    (
        "OpenCV（実際の画像処理）",
        """
        import cv2, numpy as np
        src = (np.random.RandomState(0).rand(900, 1400) * 255).astype("uint8")
        cv2.Canny(src, 60, 160)
        cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(src)
        cv2.medianBlur(src, 31)
        print("ok")
        """,
    ),
    (
        "pypdfium2（PDFの描画）",
        """
        import io
        import pypdfium2
        from PIL import Image
        # 1ページのPDFを作って、実際に描画まで通す
        buf = io.BytesIO()
        Image.new("RGB", (1650, 1000), "white").save(buf, format="PDF", resolution=200)
        pdf = pypdfium2.PdfDocument(buf.getvalue())
        pdf[0].render(scale=200 / 72).to_pil()
        pdf.close()
        print("ok")
        """,
    ),
    (
        "tesseract 本体",
        """
        import pytesseract
        print("ok", pytesseract.get_tesseract_version())
        """,
    ),
    (
        "tesseract（日本語の読み取り）",
        """
        import pytesseract
        from PIL import Image
        pytesseract.image_to_string(Image.new("RGB", (400, 120), "white"), lang="jpn")
        print("ok")
        """,
    ),
    (
        "tesseract（向き検出 OSD）",
        """
        import pytesseract
        from PIL import Image
        try:
            pytesseract.image_to_osd(Image.new("RGB", (400, 300), "white"))
        except pytesseract.TesseractError as exc:
            # 白紙では判定できなくて当然。データが無い場合だけ問題。
            if "osd" in str(exc).lower():
                raise
        print("ok")
        """,
    ),
    (
        "tesseract（縦書き言語データ jpn_vert）",
        """
        import pytesseract
        from PIL import Image
        pytesseract.image_to_string(Image.new("RGB", (400, 120), "white"), lang="jpn+jpn_vert")
        print("ok")
        """,
    ),
    (
        "tesseract（語ごとの読み取り）",
        """
        import pytesseract
        from PIL import Image
        # 本処理はこの呼び方をする。仕分け(image_to_string)とは通る経路が違う。
        for psm in (4, 6, 11):
            pytesseract.image_to_data(
                Image.new("RGB", (900, 550), "white"),
                lang="jpn+jpn_vert",
                config=f"--psm {psm}",
                output_type=pytesseract.Output.DICT,
            )
        print("ok")
        """,
    ),
    (
        "アプリの画像処理（取込と同じ経路）",
        """
        import io
        from PIL import Image
        from bcards.services.images import process_file
        buf = io.BytesIO()
        Image.new("RGB", (1650, 1000), "white").save(buf, format="JPEG")
        cards = process_file(buf.getvalue(), "sample.jpg")
        print("ok", len(cards))
        """,
    ),
    (
        "EasyOCR（併用構成のもう一方。既定で使う）",
        """
        from PIL import Image
        from bcards.services.ocr.providers import EasyOcrProvider
        out = EasyOcrProvider().recognize(Image.new("RGB", (600, 200), "white"))
        print("ok", out.api_version)
        """,
    ),
    (
        "アプリのOCR（ラベル入力と同じ経路）",
        """
        import io
        from PIL import Image
        from bcards.services.images import process_file
        from bcards.services.ocr import recognize_card
        buf = io.BytesIO()
        Image.new("RGB", (1650, 1000), "white").save(buf, format="JPEG")
        cards = process_file(buf.getvalue(), "sample.jpg")
        # 設定を上書きしないこと。既定（併用）そのままを試す。ここで
        # tesseract に固定していると、既定を変えても動作確認が追随しない。
        output, _ = recognize_card(cards[0].ocr_image)
        print("ok", output.provider, output.raw.get("engines", ""))
        """,
    ),
]

# 入っていなくても取込は止まらないもの。落ちても「使えません」と伝えるだけ。
OPTIONAL_CHECKS = {"EasyOCR（併用構成のもう一方。既定で使う）"}


APP_DIR = Path(__file__).resolve().parents[1]


def child_env() -> dict[str, str]:
    """子プロセスから `bcards` を読めるようにする。

    別のプロセスで試すため、親が通したパスは引き継がれない。渡さないと
    アプリ側の確認が必ず `ModuleNotFoundError: No module named 'bcards'`
    で落ち、**部品は動いているのに「動かない」と報告する**。診断の道具が
    嘘をつくと、そこから先の切り分けが全部むだになる。
    """
    paths = [str(APP_DIR / "src"), str(APP_DIR)]
    current = os.environ.get("PYTHONPATH")
    if current:
        paths.append(current)
    return {**os.environ, "PYTHONPATH": os.pathsep.join(paths)}


def run_check(code: str) -> tuple[int, str]:
    completed = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)],
        capture_output=True,
        text=True,
        timeout=180,
        env=child_env(),
    )
    output = (completed.stdout + completed.stderr).strip()
    return completed.returncode, output


def main() -> int:
    print("=" * 52)
    print(" 動作しない部品を探します（1つずつ別に試します）")
    print("=" * 52)
    print()

    failures: list[tuple[str, int, str]] = []
    for name, code in CHECKS:
        try:
            returncode, output = run_check(code)
        except subprocess.TimeoutExpired:
            returncode, output = -999, "時間内に終わりませんでした"

        if returncode == 0:
            print(f"  [ OK ] {name}")
            continue

        label = FATAL_CODES.get(returncode, (f"終了コード {returncode}", ""))[0]
        if name in OPTIONAL_CHECKS:
            # 入っていなくても取込は動く。ただし精度は落ちるので、
            # 「動いている」と誤解しないよう理由を書いて先へ進む。
            print(f"  [ -- ] {name}  ← 使えません")
            print("         tesseract だけで動きます（項目正答率 75.3% → 68.0%）。")
            print("         入れる場合: pip install -r requirements-combined.txt")
            continue
        print(f"  [ NG ] {name}  ← {label}")
        failures.append((name, returncode, output))

    print()
    if not failures:
        print("すべて動いています。")
        print("この結果でも症状が出る場合は、失敗した名刺のファイルを")
        print("「この1枚を調べる」に掛けた結果を共有してください。")
        return 0

    print("-" * 52)
    print(f"動かない部品が {len(failures)} 件あります。")
    print("-" * 52)
    for name, returncode, output in failures:
        label, advice = FATAL_CODES.get(returncode, (f"終了コード {returncode}", ""))
        print()
        print(f"■ {name}")
        print(f"  {label}")
        if advice:
            print(f"  {advice}")
        if output:
            print("  詳細:")
            for line in output.splitlines()[-12:]:
                print(f"    {line}")

    if any(code == -1073741795 for _, code, _ in failures):
        print()
        print("-" * 52)
        print("不正命令(0xC000001D)が出ています。次の順で試してください。")
        print()
        print(" 1) OpenCV を、古いCPUでも動く版に入れ替える")
        print("      .venv\\Scripts\\python -m pip uninstall -y opencv-python")
        print("      .venv\\Scripts\\python -m pip install opencv-python-headless==4.8.1.78")
        print()
        print(" 2) それでも直らなければ NumPy を下げる")
        print("      .venv\\Scripts\\python -m pip install \"numpy<2\"")
        print()
        print(" 3) tesseract 側が落ちている場合は、本体を入れ直す")
        print("      https://github.com/UB-Mannheim/tesseract/wiki")
        print("      （新しい版が動かないCPUでは 5.3 系を選ぶ）")
        print("-" * 52)

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
