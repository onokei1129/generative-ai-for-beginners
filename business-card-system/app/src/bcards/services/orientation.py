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

判定を誤って回すと損害が大きいため、確信度が低い回転は採用しない。ただし
確信度は取り込みの解像度で揺れる。低い場合は大きさを変えてもう一度見て、
**角度が一致すれば採る**（`detect_rotation_on_page` を参照）。割れたら回さない。
"""

from __future__ import annotations

from PIL import Image, ImageChops

# 回転を採用する確信度の下限。
# 実測: 正立の名刺 10.2 / 90度回った名刺 4.2 / 縦書き名刺 1.3〜6.0（いずれも0度と判定）。
# 0度と判定された場合は何もしないので、この下限が効くのは「回す」と判定したときだけ。
#
# ここに届かなくても、大きさを変えて同じ角度が出れば採る。取り込みの解像度が
# 低いと確信度が下限の周りで揺れるため（実テスト25枚目 0.87〜2.66）。
MIN_CONFIDENCE = 2.0

# 取り込んだページから向きを見るときの大きさ。`detect_rotation_on_page` を参照。
# 縮めるだけでなく**足りなければ伸ばす**。実テスト25枚目は 431x706 しかなく、
# 原寸のままでは確信度 0.87（下限 2.0 に届かず見送り）だった。
PAGE_PROBE_SIDE = 1600
PAGE_PROBE_SIDE_AGAIN = 1100

# 無地とみなす明るさの差。取り込みの汚れを拾わない程度に離す。
BLANK_TOLERANCE = 30


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


def trim_blank_edges(image: Image.Image) -> Image.Image:
    """周りの無地を落とす。落とせなければ元の画像をそのまま返す。

    四隅と同じ色を背景とみなし、そこから離れた画素の外接矩形で切る。
    実測 0.01〜0.04秒。名刺の輪郭検出（detect_card_quads）とは違い、
    台形の歪みは直さない——向きを見るだけならそれで足りる。
    """
    gray = image.convert("L")
    background = Image.new("L", gray.size, gray.getpixel((0, 0)))
    marks = ImageChops.difference(gray, background).point(
        lambda value: 255 if value > BLANK_TOLERANCE else 0
    )
    box = marks.getbbox()
    return image.crop(box) if box else image


def _resize_to_side(image: Image.Image, side: int) -> Image.Image:
    """長辺を `side` に合わせる。**大きすぎれば縮め、小さすぎれば伸ばす。**"""
    longest = max(image.size)
    if longest == side or longest == 0:
        return image
    scale = side / longest
    return image.resize(
        (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
        Image.LANCZOS,
    )


def detect_rotation_on_page(image: Image.Image) -> tuple[int, float]:
    """取り込んだ**ページ**から向きを読む。切り出す前の画像に使う。

    ページをそのまま縮めて渡してはいけない。ページには余白があり、名刺は
    その一部でしかない。長辺1200に縮めるとA4のページでは名刺が400px程度に
    なり、**4通りすべて判定不能になる**。実測（A4に名刺1枚、300dpi）:

        置き方   切り出した名刺の原寸    ページを1200に縮めた写し
          0度            (0, 8.24)                  (0, 0.0)
         90度          (270, 5.56)                  (0, 0.0)
        180度           (180, 8.8)                  (0, 0.0)
        270度           (90, 5.66)                  (0, 0.0)

    `(0, 0.0)` は「0度」ではなく**判定不能**。何も直せない。実テスト25枚目
    （上下逆に取り込まれた名刺）が、画面では逆さのまま出ていた。OCR側は
    切り出した名刺を見るので180度を検出できており、**同じ名刺で表示だけが
    直らない**という形で出た。

    先に余白を落とすと、字が大きいまま渡せる。実測では同じA4のページで
    4通りとも正しく検出でき、切り出し0.03秒＋検出0.3秒で済む。

    検出の要否は解像度ではなく**名刺の大きさ**で決まる。実測では横幅
    600px を下回ると判定不能になり、それ以上ならどの大きさでも 0.3〜0.6秒:

        400px 判定不能 / 600px (180, 2.38) / 1000px (180, 8.34) / 2560px (180, 9.8)

    小さすぎるページは伸ばす
    ------------------------
    実テスト25枚目は **431x706 しかなかった**。取り込みの解像度が低い名刺で、
    原寸のままでは確信度が下限に届かない。答えのほうは合っている:

        長辺 706  (270, 0.87)  見送り  ← 原寸
        長辺1000  (270, 2.59)  採用
        長辺1400  (270, 2.06)  採用
        長辺1800  (270, 2.66)  採用
        長辺2200  (270, 1.95)  見送り
        長辺2800  (270, 2.44)  採用

    **角度はどの大きさでも 270 で変わらないのに、確信度だけが下限の周りで
    揺れている。** 1回の確信度で決めると、同じ名刺が採用されたり見送られたり
    する。そこで、確信度が足りないときは**別の大きさでもう一度見て、角度が
    一致すれば採る**。答えが大きさに依らないことのほうが、1回の確信度より
    確かな手がかりになる。

    0度と判定されたときは何もしないので、この念押しが効くのは「回す」と
    判定したときだけ。縦書き名刺は0度と判定されるため巻き添えにならない。
    """
    trimmed = trim_blank_edges(image)

    degrees, confidence = detect_rotation(_resize_to_side(trimmed, PAGE_PROBE_SIDE))
    if degrees == 0 or confidence >= MIN_CONFIDENCE:
        return degrees, confidence

    # 確信度が足りない。別の大きさで同じ答えになるなら採る。
    again, again_confidence = detect_rotation(
        _resize_to_side(trimmed, PAGE_PROBE_SIDE_AGAIN)
    )
    if again == degrees:
        return degrees, max(confidence, again_confidence, MIN_CONFIDENCE)
    return degrees, confidence


def upright(image: Image.Image) -> tuple[Image.Image, int]:
    """90度単位で回った画像を正立させる。回さなかった場合は0度を返す。

    判定は `detect_rotation_on_page` に任せる。原寸をそのまま渡すと、
    取り込みの解像度が低い名刺で確信度が下限に届かず、**正しい答えを
    見送る**。実テスト25枚目（431x706）がこれで、向きが直らないまま
    OCRに渡り、読めないので回してやり直す、を繰り返して1枚に141.9秒
    かかっていた（子プロセスの制限は120秒なので打ち切られる）。
    """
    degrees, confidence = detect_rotation_on_page(image)
    if degrees == 0 or confidence < MIN_CONFIDENCE:
        return image, 0
    # OSDの rotate は「この角度だけ回すと正立する（時計回り）」。
    # PIL の rotate は反時計回りなので符号を反転する。
    return image.rotate(-degrees, expand=True), degrees
