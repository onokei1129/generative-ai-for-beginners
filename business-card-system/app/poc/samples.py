"""PoC用の評価サンプル生成（正解ラベル付き）。

実名刺を使えない環境でもOCR精度を数値で比較できるよう、
正解が分かっている名刺画像をレイアウト違い・撮影条件違いで生成する。

実データでPoCを行う場合は load_real_samples() を使い、
poc/samples/ に画像と同名の .json（正解ラベル）を置く。
open-issues-v0.3.md 論点C の「PoC用サンプル名刺30〜50枚」に相当する。
"""

from __future__ import annotations

import io
import json
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFont

from bcards import fonts

# フォントの実体は環境ごとに違うため、ここでは種類だけを表す印を置き、
# _font() が呼ばれた時点で解決する。import しただけでフォントを要求しないのは、
# 正解ラベル入力（poc/label.py）が FIELD_KEYS だけを使うため。
FONT_GOTHIC = "gothic"
FONT_LATIN = "latin"

FIELD_KEYS = (
    "last_name",
    "first_name",
    "last_name_kana",
    "first_name_kana",
    "company_name",
    "department_name",
    "title",
    "postal_code",
    "address",
    "tel",
    "mobile",
    "fax",
    "email",
    "url",
)


@dataclass
class Sample:
    sample_id: str
    variant: str
    image: Image.Image
    truth: dict[str, str] = field(default_factory=dict)


# かな1音ずつのローマ字。日英併記の名刺に刷るローマ字を作るために使う。
_KANA = {
    "きゃ": "kya", "きゅ": "kyu", "きょ": "kyo", "しゃ": "sha", "しゅ": "shu", "しょ": "sho",
    "ちゃ": "cha", "ちゅ": "chu", "ちょ": "cho", "にゃ": "nya", "にゅ": "nyu", "にょ": "nyo",
    "ひゃ": "hya", "ひゅ": "hyu", "ひょ": "hyo", "みゃ": "mya", "みゅ": "myu", "みょ": "myo",
    "りゃ": "rya", "りゅ": "ryu", "りょ": "ryo", "ぎゃ": "gya", "ぎゅ": "gyu", "ぎょ": "gyo",
    "じゃ": "ja", "じゅ": "ju", "じょ": "jo", "びゃ": "bya", "びゅ": "byu", "びょ": "byo",
    "ぴゃ": "pya", "ぴゅ": "pyu", "ぴょ": "pyo",
    "あ": "a", "い": "i", "う": "u", "え": "e", "お": "o",
    "か": "ka", "き": "ki", "く": "ku", "け": "ke", "こ": "ko",
    "が": "ga", "ぎ": "gi", "ぐ": "gu", "げ": "ge", "ご": "go",
    "さ": "sa", "し": "shi", "す": "su", "せ": "se", "そ": "so",
    "ざ": "za", "じ": "ji", "ず": "zu", "ぜ": "ze", "ぞ": "zo",
    "た": "ta", "ち": "chi", "つ": "tsu", "て": "te", "と": "to",
    "だ": "da", "ぢ": "ji", "づ": "zu", "で": "de", "ど": "do",
    "な": "na", "に": "ni", "ぬ": "nu", "ね": "ne", "の": "no",
    "は": "ha", "ひ": "hi", "ふ": "fu", "へ": "he", "ほ": "ho",
    "ば": "ba", "び": "bi", "ぶ": "bu", "べ": "be", "ぼ": "bo",
    "ぱ": "pa", "ぴ": "pi", "ぷ": "pu", "ぺ": "pe", "ぽ": "po",
    "ま": "ma", "み": "mi", "む": "mu", "め": "me", "も": "mo",
    "や": "ya", "ゆ": "yu", "よ": "yo",
    "ら": "ra", "り": "ri", "る": "ru", "れ": "re", "ろ": "ro",
    "わ": "wa", "を": "o", "ん": "n",
}


def to_romaji(kana: str) -> str:
    """かなを、名刺に刷られる形のローマ字にする。

    **長音を落とす。** 名刺のローマ字は旅券式のヘボンで刷られ、`さとう` は
    `Sato`、`いとう` は `Ito`、`たろう` は `Taro` になる。合成名刺にだけ
    `Satou` と刷ってしまうと、ここから読みを起こす仕掛け
    （`_fill_kana_from_romaji`）が、実物では起きない好条件で測られる。
    実物223枚がそう刷られている以上、合成でもそう刷る。
    """
    out, i = "", 0
    while i < len(kana):
        if kana[i] == "っ":
            nxt = to_romaji(kana[i + 1 :])
            return out + (nxt[0] if nxt else "") + nxt
        pair = kana[i : i + 2]
        if pair in _KANA:
            out += _KANA[pair]
            i += 2
            continue
        out += _KANA.get(kana[i], kana[i])
        i += 1
    # 旅券式の長音。`ou`→`o`、`oo`→`o`、`uu`→`u`。`ii` は残す（新潟＝Niigata）。
    for double, single in (("ou", "o"), ("oo", "o"), ("uu", "u")):
        out = out.replace(double, single)
    return out


def printed_romaji(person: dict[str, str]) -> str:
    """名刺に刷るローマ字の行。並びは名刺ごとに違う。

    実物では両方の並びが使われている。24枚目は `Nakaji Kimura`（名 姓）、
    35枚目は `Kasama Shinichiro`（姓 名）。片方だけで測ると、並びを
    取り違える誤りが表に出ない。
    """
    last = to_romaji(person["last_name_kana"]).capitalize()
    first = to_romaji(person["first_name_kana"]).capitalize()
    if person.get("romaji_order") == "first_last":
        return f"{first} {last}"
    return f"{last} {first}"


PEOPLE: list[dict[str, str]] = [
    {
        "last_name": "山田", "first_name": "太郎", "last_name_kana": "やまだ", "first_name_kana": "たろう", "romaji_order": "last_first",
        "company_name": "株式会社サンプル商事", "department_name": "営業本部 第一営業部", "title": "部長",
        "postal_code": "100-0001", "address": "東京都千代田区千代田1-1-1",
        "tel": "03-1234-5678", "mobile": "090-1234-5678", "fax": "03-1234-5679",
        "email": "taro.yamada@example.co.jp", "url": "https://www.example.co.jp",
    },
    {
        "last_name": "佐藤", "first_name": "花子", "last_name_kana": "さとう", "first_name_kana": "はなこ", "romaji_order": "first_last",
        "company_name": "テクノロジー株式会社", "department_name": "開発部", "title": "主任",
        "postal_code": "530-0001", "address": "大阪府大阪市北区梅田2-2-2",
        "tel": "06-9876-5432", "mobile": "080-2222-3333", "fax": "",
        "email": "hanako.sato@example.jp", "url": "https://tech.example.jp",
    },
    {
        "last_name": "鈴木", "first_name": "一郎", "last_name_kana": "すずき", "first_name_kana": "いちろう", "romaji_order": "last_first",
        "company_name": "合同会社みらいデザイン", "department_name": "クリエイティブ室", "title": "代表社員",
        "postal_code": "460-0008", "address": "愛知県名古屋市中区栄3-3-3",
        "tel": "052-111-2222", "mobile": "", "fax": "052-111-2223",
        "email": "ichiro@mirai.example", "url": "",
    },
    {
        "last_name": "田中", "first_name": "健二", "last_name_kana": "たなか", "first_name_kana": "けんじ", "romaji_order": "first_last",
        "company_name": "株式会社ロジスティクス九州", "department_name": "物流企画部", "title": "課長",
        "postal_code": "812-0011", "address": "福岡県福岡市博多区博多駅前4-4-4",
        "tel": "092-333-4444", "mobile": "070-4444-5555", "fax": "",
        "email": "tanaka@logi-kyushu.example", "url": "https://logi-kyushu.example",
    },
    {
        "last_name": "高橋", "first_name": "美咲", "last_name_kana": "たかはし", "first_name_kana": "みさき", "romaji_order": "last_first",
        "company_name": "北海道フーズ株式会社", "department_name": "商品開発部", "title": "係長",
        "postal_code": "060-0001", "address": "北海道札幌市中央区北一条西5-5-5",
        "tel": "011-555-6666", "mobile": "090-6666-7777", "fax": "011-555-6667",
        "email": "takahashi@hokkaido-foods.example", "url": "",
    },
    {
        "last_name": "伊藤", "first_name": "直樹", "last_name_kana": "いとう", "first_name_kana": "なおき", "romaji_order": "first_last",
        "company_name": "一般社団法人日本データ協会", "department_name": "調査研究センター", "title": "主任研究員",
        "postal_code": "150-0002", "address": "東京都渋谷区渋谷6-6-6",
        "tel": "03-7777-8888", "mobile": "", "fax": "03-7777-8889",
        "email": "ito@jda.example", "url": "https://jda.example",
    },
    {
        # 名が3文字の人。姓と名の字数が違う名刺が1枚も無いと、ローマ字の
        # 並びを取り違えても表に出ない（実物35枚目 `Kasama Shinichiro` の形）。
        "last_name": "中村", "first_name": "陽一郎", "last_name_kana": "なかむら",
        "first_name_kana": "よういちろう", "romaji_order": "last_first",
        "company_name": "中村精密工業株式会社", "department_name": "生産技術部", "title": "工場長",
        "postal_code": "460-0008", "address": "愛知県名古屋市中区栄3-15-33",
        "tel": "052-222-3333", "mobile": "090-4444-5555", "fax": "052-222-3334",
        "email": "y.nakamura@nakamura-seimitsu.example", "url": "",
    },
]


def _font(kind: str, size: int) -> ImageFont.FreeTypeFont:
    """FONT_GOTHIC / FONT_LATIN を実際のフォントに解決する。"""
    return fonts.load(size, latin=(kind == FONT_LATIN))


def _base_card(width: int = 1050, height: int = 630, bg: str = "white") -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (width, height), bg)
    return image, ImageDraw.Draw(image)


# --------------------------------------------------------------------------
# レイアウト
# --------------------------------------------------------------------------


def render_standard(person: dict[str, str]) -> Image.Image:
    """一般的な横書きレイアウト。"""
    image, draw = _base_card()
    draw.rectangle([0, 0, 12, image.height], fill="#1f5fa9")

    y = 58
    draw.text((70, y), person["company_name"], font=_font(FONT_GOTHIC, 40), fill="#111111")
    y += 62
    draw.text((70, y), person["department_name"], font=_font(FONT_GOTHIC, 24), fill="#333333")
    y += 36
    draw.text((70, y), person["title"], font=_font(FONT_GOTHIC, 24), fill="#333333")
    y += 52
    draw.text((70, y), f"{person['last_name_kana']} {person['first_name_kana']}",
              font=_font(FONT_GOTHIC, 22), fill="#666666")
    y += 32
    draw.text((70, y), f"{person['last_name']} {person['first_name']}",
              font=_font(FONT_GOTHIC, 52), fill="#111111")

    y = 424
    draw.text((70, y), f"〒{person['postal_code']} {person['address']}", font=_font(FONT_GOTHIC, 22), fill="#222222")
    y += 34
    line = f"TEL {person['tel']}"
    if person["fax"]:
        line += f"　FAX {person['fax']}"
    draw.text((70, y), line, font=_font(FONT_GOTHIC, 22), fill="#222222")
    y += 34
    if person["mobile"]:
        draw.text((70, y), f"Mobile {person['mobile']}", font=_font(FONT_GOTHIC, 22), fill="#222222")
        y += 34
    tail = person["email"] + (f"　{person['url']}" if person["url"] else "")
    draw.text((70, y), tail, font=_font(FONT_GOTHIC, 22), fill="#222222")
    return image


def render_bilingual(person: dict[str, str]) -> Image.Image:
    """日英併記レイアウト（右側にローマ字表記）。"""
    image, draw = _base_card()
    draw.line([(0, 96), (image.width, 96)], fill="#c8ccd2", width=2)

    draw.text((60, 34), person["company_name"], font=_font(FONT_GOTHIC, 36), fill="#111111")
    romaji = printed_romaji(person)
    draw.text((60, 132), person["department_name"], font=_font(FONT_GOTHIC, 22), fill="#444444")
    draw.text((60, 168), person["title"], font=_font(FONT_GOTHIC, 22), fill="#444444")
    draw.text((60, 226), f"{person['last_name']} {person['first_name']}",
              font=_font(FONT_GOTHIC, 46), fill="#111111")
    draw.text((62, 292), romaji, font=_font(FONT_LATIN, 20), fill="#777777")

    x = 560
    draw.text((x, 132), "Head Office", font=_font(FONT_LATIN, 18), fill="#777777")
    draw.text((x, 162), f"〒{person['postal_code']}", font=_font(FONT_GOTHIC, 20), fill="#222222")
    draw.text((x, 192), person["address"], font=_font(FONT_GOTHIC, 20), fill="#222222")
    draw.text((x, 236), f"TEL {person['tel']}", font=_font(FONT_GOTHIC, 20), fill="#222222")
    if person["fax"]:
        draw.text((x, 266), f"FAX {person['fax']}", font=_font(FONT_GOTHIC, 20), fill="#222222")
    if person["mobile"]:
        draw.text((x, 296), f"Mobile {person['mobile']}", font=_font(FONT_GOTHIC, 20), fill="#222222")
    draw.text((x, 336), person["email"], font=_font(FONT_LATIN, 20), fill="#222222")
    if person["url"]:
        draw.text((x, 366), person["url"], font=_font(FONT_LATIN, 20), fill="#222222")

    draw.text((60, 470), f"{person['last_name_kana']} {person['first_name_kana']}",
              font=_font(FONT_GOTHIC, 20), fill="#666666")
    return image


def _draw_vertical(draw: ImageDraw.ImageDraw, x: int, y: int, text: str, font, fill: str, spacing: int = 6) -> int:
    """縦書きで1列描画し、次のY位置を返す。"""
    cursor = y
    for char in text:
        draw.text((x, cursor), char, font=font, fill=fill)
        cursor += font.size + spacing
    return cursor


def render_vertical(person: dict[str, str]) -> Image.Image:
    """縦書きレイアウト（右から左へ列を配置）。"""
    image, draw = _base_card(width=630, height=1050)
    draw.rectangle([0, 0, image.width, 10], fill="#8a1f2d")

    x = image.width - 90
    _draw_vertical(draw, x, 70, f"{person['last_name']}{person['first_name']}", _font(FONT_GOTHIC, 46), "#111111")
    x -= 74
    _draw_vertical(draw, x, 80, person["title"], _font(FONT_GOTHIC, 26), "#333333")
    x -= 46
    _draw_vertical(draw, x, 80, person["department_name"].replace(" ", ""), _font(FONT_GOTHIC, 26), "#333333")
    x -= 46
    _draw_vertical(draw, x, 70, person["company_name"], _font(FONT_GOTHIC, 34), "#111111")

    # 連絡先は下部に横書き（実際の縦書き名刺でも多い形式）
    y = image.height - 190
    draw.text((60, y), f"〒{person['postal_code']} {person['address']}", font=_font(FONT_GOTHIC, 19), fill="#222222")
    y += 30
    line = f"TEL {person['tel']}"
    if person["fax"]:
        line += f"　FAX {person['fax']}"
    draw.text((60, y), line, font=_font(FONT_GOTHIC, 19), fill="#222222")
    y += 30
    if person["mobile"]:
        draw.text((60, y), f"携帯 {person['mobile']}", font=_font(FONT_GOTHIC, 19), fill="#222222")
        y += 30
    draw.text((60, y), person["email"], font=_font(FONT_LATIN, 19), fill="#222222")
    return image


def render_decorated(person: dict[str, str]) -> Image.Image:
    """色地・ロゴ的な図形を含むレイアウト。"""
    image, draw = _base_card(bg="#f3f1ec")
    draw.rectangle([0, 0, image.width, 150], fill="#20303f")
    draw.ellipse([64, 40, 134, 110], fill="#e0a33c")
    draw.text((156, 58), person["company_name"], font=_font(FONT_GOTHIC, 36), fill="#ffffff")

    draw.text((70, 210), f"{person['last_name_kana']} {person['first_name_kana']}",
              font=_font(FONT_GOTHIC, 20), fill="#7a7a7a")
    draw.text((70, 240), f"{person['last_name']} {person['first_name']}",
              font=_font(FONT_GOTHIC, 50), fill="#20303f")
    draw.text((70, 314), f"{person['department_name']}　{person['title']}",
              font=_font(FONT_GOTHIC, 22), fill="#4a4a4a")

    draw.line([(70, 372), (image.width - 70, 372)], fill="#c9c2b4", width=2)
    y = 396
    draw.text((70, y), f"〒{person['postal_code']} {person['address']}", font=_font(FONT_GOTHIC, 21), fill="#333333")
    y += 32
    line = f"TEL {person['tel']}"
    if person["fax"]:
        line += f"　FAX {person['fax']}"
    if person["mobile"]:
        line += f"　携帯 {person['mobile']}"
    draw.text((70, y), line, font=_font(FONT_GOTHIC, 21), fill="#333333")
    y += 32
    tail = person["email"] + (f"　{person['url']}" if person["url"] else "")
    draw.text((70, y), tail, font=_font(FONT_GOTHIC, 21), fill="#333333")
    return image


def render_spread(person: dict[str, str]) -> Image.Image:
    """姓と名を大きく離し、ふりがなをそれぞれの上に置くレイアウト。

    実データ（官公庁の名刺2枚）でこの体裁に当たり、氏名とふりがなが
    総崩れになった。離れて印字された分がOCRでは**別々の行**として読まれる。

        印字  とみた　　おさむ      読み  とみた / おさむ / 冨田 / 修
              冨田　　　修

    QRコードとロゴも入れる。実データではこれらが `回回` `© ` のような
    文字として読まれ、住所や会社名の前後に付いていた。

    合成サンプルに無い体裁は、実名刺を見るまで気づけない。気づいたものは
    ここに足して、次からは自動で検知できるようにする。
    """
    image, draw = _base_card(bg="#ffffff")

    # 社名は左、ロゴ（丸）は右端。実データもこの並びで、ロゴは `©` のような
    # 文字として読まれる。社名に重ねると社名まで読めなくなり、サンプルとして
    # 厳しすぎるため離して置く。
    draw.text((70, 52), person["company_name"], font=_font(FONT_GOTHIC, 38), fill="#111111")
    draw.ellipse([900, 40, 980, 120], fill="#d93a2b")
    draw.ellipse([924, 64, 956, 96], fill="#ffffff")

    # 部署・役職は左、氏名は右。姓と名は大きく離す
    draw.text((70, 210), person["department_name"], font=_font(FONT_GOTHIC, 26), fill="#222222")
    draw.text((70, 254), person["title"], font=_font(FONT_GOTHIC, 26), fill="#222222")

    draw.text((560, 186), person["last_name_kana"], font=_font(FONT_GOTHIC, 22), fill="#555555")
    draw.text((790, 186), person["first_name_kana"], font=_font(FONT_GOTHIC, 22), fill="#555555")
    draw.text((548, 224), person["last_name"], font=_font(FONT_GOTHIC, 54), fill="#111111")
    draw.text((790, 224), person["first_name"], font=_font(FONT_GOTHIC, 54), fill="#111111")

    # QRコード風の市松模様
    for row in range(7):
        for column in range(7):
            if (row * 3 + column * 5) % 4 < 2:
                x, y = 74 + column * 22, 396 + row * 22
                draw.rectangle([x, y, x + 20, y + 20], fill="#111111")

    y = 396
    draw.text((260, y), f"〒{person['postal_code']} {person['address']}",
              font=_font(FONT_GOTHIC, 21), fill="#222222")
    y += 34
    draw.text((260, y), f"T E L : {person['tel']}", font=_font(FONT_GOTHIC, 21), fill="#222222")
    y += 34
    if person["fax"]:
        draw.text((260, y), f"F A X : {person['fax']}", font=_font(FONT_GOTHIC, 21), fill="#222222")
        y += 34
    if person["mobile"]:
        draw.text((70, 320), f"携帯 {person['mobile']}", font=_font(FONT_GOTHIC, 21), fill="#222222")
    draw.text((260, y), f"E-mail : {person['email']}", font=_font(FONT_GOTHIC, 21), fill="#222222")
    if person["url"]:
        draw.text((640, 464), person["url"], font=_font(FONT_GOTHIC, 21), fill="#222222")
    return image


LAYOUTS = {
    "standard": render_standard,
    "bilingual": render_bilingual,
    "vertical": render_vertical,
    "decorated": render_decorated,
    "spread": render_spread,
}


# --------------------------------------------------------------------------
# 撮影条件のシミュレーション
# --------------------------------------------------------------------------


def as_scan(image: Image.Image) -> Image.Image:
    """複合機スキャン相当：わずかなノイズと余白。"""
    canvas = Image.new("RGB", (image.width + 60, image.height + 60), "#fbfbfb")
    canvas.paste(image, (30, 30))
    array = np.array(canvas).astype(np.int16)
    array += np.random.default_rng(1).integers(-4, 5, array.shape, dtype=np.int16)
    return Image.fromarray(np.clip(array, 0, 255).astype(np.uint8))


def as_phone_photo(image: Image.Image, seed: int = 0) -> Image.Image:
    """スマートフォン撮影相当：傾き・影・低解像度・軽いぼけ。"""
    rng = random.Random(seed)
    canvas = Image.new("RGB", (int(image.width * 1.35), int(image.height * 1.45)), (206, 204, 200))
    canvas.paste(image, ((canvas.width - image.width) // 2, (canvas.height - image.height) // 2))
    canvas = canvas.rotate(rng.uniform(-7, 7), resample=Image.BICUBIC, expand=True, fillcolor=(206, 204, 200))

    # 斜めからの光による影のグラデーション
    array = np.array(canvas).astype(np.float32)
    height, width = array.shape[:2]
    gradient = np.linspace(0.72, 1.05, width, dtype=np.float32)[None, :, None]
    vertical = np.linspace(1.03, 0.86, height, dtype=np.float32)[:, None, None]
    array = np.clip(array * gradient * vertical, 0, 255)
    result = Image.fromarray(array.astype(np.uint8))

    # 解像度を落としてから戻す（スマホ撮影＋圧縮相当）
    small = result.resize((int(result.width * 0.55), int(result.height * 0.55)), Image.LANCZOS)
    result = small.resize(result.size, Image.BICUBIC)
    result = ImageEnhance.Sharpness(result).enhance(0.75)

    buffer = io.BytesIO()
    result.save(buffer, format="JPEG", quality=72)
    return Image.open(buffer).convert("RGB")


CONDITIONS = {
    "scan": lambda image, seed: as_scan(image),
    "photo": as_phone_photo,
}


def build_samples(count: int | None = None) -> list[Sample]:
    """レイアウト×撮影条件の組み合わせでサンプルを作る。"""
    samples: list[Sample] = []
    index = 0
    for layout_name, render in LAYOUTS.items():
        for condition_name, apply_condition in CONDITIONS.items():
            person = PEOPLE[index % len(PEOPLE)]
            image = apply_condition(render(person), index)
            samples.append(
                Sample(
                    sample_id=f"{layout_name}-{condition_name}-{index:02d}",
                    variant=f"{layout_name}/{condition_name}",
                    image=image,
                    truth={key: person.get(key, "") for key in FIELD_KEYS},
                )
            )
            index += 1
    # 人物の組み合わせを変えた2周目（同じ枚数で人物バリエーションを増やす）
    for layout_name, render in LAYOUTS.items():
        for condition_name, apply_condition in CONDITIONS.items():
            person = PEOPLE[(index + 3) % len(PEOPLE)]
            image = apply_condition(render(person), index)
            samples.append(
                Sample(
                    sample_id=f"{layout_name}-{condition_name}-{index:02d}",
                    variant=f"{layout_name}/{condition_name}",
                    image=image,
                    truth={key: person.get(key, "") for key in FIELD_KEYS},
                )
            )
            index += 1
    if count is not None:
        samples = samples[:count]
    return samples


def load_real_samples(directory: Path) -> list[Sample]:
    """実名刺でPoCを行う場合の読み込み。

    directory 内に card01.jpg と card01.json（正解ラベル）を対で置く。
    """
    samples: list[Sample] = []
    unverified: set[str] = set()
    unverified_files = 0
    for image_path in sorted(directory.glob("*")):
        if image_path.suffix.lower() not in (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".heic"):
            continue
        label_path = image_path.with_suffix(".json")
        if not label_path.exists():
            continue
        truth: dict[str, Any] = json.loads(label_path.read_text(encoding="utf-8"))
        unverified.update(truth.get("_unverified") or [])
        if truth.get("_unverified"):
            unverified_files += 1
        samples.append(
            Sample(
                sample_id=image_path.stem,
                variant="real",
                image=Image.open(image_path).convert("RGB"),
                truth={key: str(truth.get(key, "") or "") for key in FIELD_KEYS},
            )
        )

    if unverified_files:
        # OCRの下書きをそのまま正解にしていると、その分だけ数値が良く出る。
        # 黙って測ると気づけないため、必ず知らせる。
        print(
            f"\n【注意】{unverified_files} 件の正解ラベルに、人が確認していない項目が含まれています。\n"
            f"  該当項目: {'、'.join(sorted(unverified))}\n"
            "  これらはOCRの下書きがそのまま正解になっているため、\n"
            "  精度が実際より良く出ます。入力画面で黄色の欄を確認してください。\n",
            file=sys.stderr,
        )
    return samples


def save_samples(samples: list[Sample], directory: Path) -> None:
    """生成したサンプルを画像として保存する（目視確認用）。"""
    directory.mkdir(parents=True, exist_ok=True)
    for sample in samples:
        sample.image.save(directory / f"{sample.sample_id}.jpg", quality=92)
        (directory / f"{sample.sample_id}.json").write_text(
            json.dumps(sample.truth, ensure_ascii=False, indent=2), encoding="utf-8"
        )


__all__ = ["Sample", "FIELD_KEYS", "build_samples", "load_real_samples", "save_samples"]
