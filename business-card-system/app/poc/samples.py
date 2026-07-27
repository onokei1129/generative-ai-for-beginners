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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFont

FONT_GOTHIC = "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf"
FONT_LATIN = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

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


PEOPLE: list[dict[str, str]] = [
    {
        "last_name": "山田", "first_name": "太郎", "last_name_kana": "やまだ", "first_name_kana": "たろう",
        "company_name": "株式会社サンプル商事", "department_name": "営業本部 第一営業部", "title": "部長",
        "postal_code": "100-0001", "address": "東京都千代田区千代田1-1-1",
        "tel": "03-1234-5678", "mobile": "090-1234-5678", "fax": "03-1234-5679",
        "email": "taro.yamada@example.co.jp", "url": "https://www.example.co.jp",
    },
    {
        "last_name": "佐藤", "first_name": "花子", "last_name_kana": "さとう", "first_name_kana": "はなこ",
        "company_name": "テクノロジー株式会社", "department_name": "開発部", "title": "主任",
        "postal_code": "530-0001", "address": "大阪府大阪市北区梅田2-2-2",
        "tel": "06-9876-5432", "mobile": "080-2222-3333", "fax": "",
        "email": "hanako.sato@example.jp", "url": "https://tech.example.jp",
    },
    {
        "last_name": "鈴木", "first_name": "一郎", "last_name_kana": "すずき", "first_name_kana": "いちろう",
        "company_name": "合同会社みらいデザイン", "department_name": "クリエイティブ室", "title": "代表社員",
        "postal_code": "460-0008", "address": "愛知県名古屋市中区栄3-3-3",
        "tel": "052-111-2222", "mobile": "", "fax": "052-111-2223",
        "email": "ichiro@mirai.example", "url": "",
    },
    {
        "last_name": "田中", "first_name": "健二", "last_name_kana": "たなか", "first_name_kana": "けんじ",
        "company_name": "株式会社ロジスティクス九州", "department_name": "物流企画部", "title": "課長",
        "postal_code": "812-0011", "address": "福岡県福岡市博多区博多駅前4-4-4",
        "tel": "092-333-4444", "mobile": "070-4444-5555", "fax": "",
        "email": "tanaka@logi-kyushu.example", "url": "https://logi-kyushu.example",
    },
    {
        "last_name": "高橋", "first_name": "美咲", "last_name_kana": "たかはし", "first_name_kana": "みさき",
        "company_name": "北海道フーズ株式会社", "department_name": "商品開発部", "title": "係長",
        "postal_code": "060-0001", "address": "北海道札幌市中央区北一条西5-5-5",
        "tel": "011-555-6666", "mobile": "090-6666-7777", "fax": "011-555-6667",
        "email": "takahashi@hokkaido-foods.example", "url": "",
    },
    {
        "last_name": "伊藤", "first_name": "直樹", "last_name_kana": "いとう", "first_name_kana": "なおき",
        "company_name": "一般社団法人日本データ協会", "department_name": "調査研究センター", "title": "主任研究員",
        "postal_code": "150-0002", "address": "東京都渋谷区渋谷6-6-6",
        "tel": "03-7777-8888", "mobile": "", "fax": "03-7777-8889",
        "email": "ito@jda.example", "url": "https://jda.example",
    },
]


def _font(path: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, size)


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
    romaji = f"{person['first_name_kana'].upper()} {person['last_name_kana'].upper()}"
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


LAYOUTS = {
    "standard": render_standard,
    "bilingual": render_bilingual,
    "vertical": render_vertical,
    "decorated": render_decorated,
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
    for image_path in sorted(directory.glob("*")):
        if image_path.suffix.lower() not in (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".heic"):
            continue
        label_path = image_path.with_suffix(".json")
        if not label_path.exists():
            continue
        truth: dict[str, Any] = json.loads(label_path.read_text(encoding="utf-8"))
        samples.append(
            Sample(
                sample_id=image_path.stem,
                variant="real",
                image=Image.open(image_path).convert("RGB"),
                truth={key: str(truth.get(key, "") or "") for key in FIELD_KEYS},
            )
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
