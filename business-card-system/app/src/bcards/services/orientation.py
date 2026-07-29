"""スキャンした名刺の「90度単位の向き」を直す。

読み取り機に横向きに置いた名刺は、画像そのものが90度回った状態で入ってくる。
人が見れば読めるので気づきにくいが、OCRにとっては別物で、実測では
1枚から取れる項目が **14項目 → 2項目** まで落ちた。

傾き補正（images.deskew）が直すのは数度のズレで、90度は対象外。
そこで tesseract の向き検出（OSD）で 90度単位の回転だけを別に直す。

縦書き名刺を巻き添えにしないこと
--------------------------------
「縦長だから回す」という形だけの判定は、縦書き名刺のOCRを壊すことが
PoCで分かっている（ocr-poc-report.md 4.2「不採用」）。OSDは字の形から
向きを読むため、縦書き名刺は正立と判定される。PoCサンプル16枚
（縦書きの scan/photo を含む）は全て回転0度と判定されることを確認済み。

判定を誤って回すと損害が大きいため、確信度が低い回転は採用しない。
"""

from __future__ import annotations

from PIL import Image

# 回転を採用する確信度の下限。
# 実測: 正立の名刺 10.2 / 90度回った名刺 4.2 / 縦書き名刺 1.3〜6.0（いずれも0度と判定）。
# 0度と判定された場合は何もしないので、この下限が効くのは「回す」と判定したときだけ。
MIN_CONFIDENCE = 2.0


def detect_rotation(image: Image.Image) -> tuple[int, float]:
    """時計回りに何度戻せば正立するかと、その確信度を返す。

    判定できない場合（向き検出用データが無い、文字が少なすぎる等）は (0, 0.0)。
    OCRを止める理由にはならないため、例外にはしない。
    """
    try:
        import pytesseract

        osd = pytesseract.image_to_osd(image, output_type=pytesseract.Output.DICT)
    except Exception:  # 向き検出用データ(osd)が無い環境・文字が少ない画像など
        return 0, 0.0

    try:
        degrees = int(osd.get("rotate", 0)) % 360
        confidence = float(osd.get("orientation_conf", 0.0))
    except (TypeError, ValueError):
        return 0, 0.0

    if degrees not in (0, 90, 180, 270):
        return 0, 0.0
    return degrees, confidence


def upright(image: Image.Image) -> tuple[Image.Image, int]:
    """90度単位で回った画像を正立させる。回さなかった場合は0度を返す。"""
    degrees, confidence = detect_rotation(image)
    if degrees == 0 or confidence < MIN_CONFIDENCE:
        return image, 0
    # OSDの rotate は「この角度だけ回すと正立する（時計回り）」。
    # PIL の rotate は反時計回りなので符号を反転する。
    return image.rotate(-degrees, expand=True), degrees
