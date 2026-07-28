"""仕分け（poc/classify.py）を検証するための領収書サンプル生成。

実データを持ち込めない環境でも、名刺と領収書が混在したフォルダを再現して
仕分けの正答率を数値で確認できるようにする。

    PYTHONPATH=src .venv/bin/python -m poc.receipts --out /tmp/mixed

生成されるもの:

- 名刺（poc/samples.py の合成サンプル）
- レシート形状の領収書（細長い）
- A4形状の領収書・請求書

ファイル名には正解が入らないようにし、正解は `_truth.csv` に別で書き出す。
"""

from __future__ import annotations

import argparse
import csv
import random
from pathlib import Path

from PIL import Image, ImageDraw

from .samples import FONT_GOTHIC, FONT_LATIN, _font, build_samples

SHOPS = [
    ("コーヒースタンド銀座", "東京都中央区銀座4-1-1", "03-3535-1111"),
    ("スーパーマルヤマ 本店", "大阪府大阪市北区梅田1-2-3", "06-6300-2222"),
    ("文具のタカハシ", "愛知県名古屋市中区栄2-4-6", "052-201-3333"),
    ("тヤマダ書店 駅前店", "福岡県福岡市博多区博多駅前3-1-1", "092-431-4444"),
]

ITEMS = [
    ("ブレンドコーヒー", 480), ("サンドイッチ", 620), ("コピー用紙A4", 780),
    ("ボールペン(黒)", 165), ("ノート B5", 220), ("USBメモリ 32GB", 1480),
    ("клипファイル", 350), ("付箋 3色", 298), ("宅配便 発送", 940),
]


def render_receipt_slip(seed: int) -> Image.Image:
    """レジのレシート。細長く、明細と合計が並ぶ。"""
    rng = random.Random(seed)
    shop, address, tel = rng.choice(SHOPS)
    items = rng.sample(ITEMS, k=rng.randint(3, 6))

    width = 620
    height = 420 + 46 * len(items)
    image = Image.new("RGB", (width, height), "#fdfdfb")
    draw = ImageDraw.Draw(image)

    y = 30
    draw.text((40, y), shop, font=_font(FONT_GOTHIC, 30), fill="#111111")
    y += 44
    draw.text((40, y), address, font=_font(FONT_GOTHIC, 19), fill="#333333")
    y += 30
    draw.text((40, y), f"TEL {tel}", font=_font(FONT_GOTHIC, 19), fill="#333333")
    y += 30
    draw.text((40, y), f"登録番号 T{rng.randint(10**12, 10**13 - 1)}", font=_font(FONT_GOTHIC, 18), fill="#333333")
    y += 40
    draw.line([(30, y), (width - 30, y)], fill="#999999", width=2)
    y += 24

    draw.text((40, y), "領 収 書", font=_font(FONT_GOTHIC, 32), fill="#111111")
    y += 56

    subtotal = 0
    for name, price in items:
        qty = rng.randint(1, 3)
        amount = price * qty
        subtotal += amount
        draw.text((40, y), f"{name}", font=_font(FONT_GOTHIC, 22), fill="#222222")
        draw.text((width - 220, y), f"数量 {qty}", font=_font(FONT_GOTHIC, 20), fill="#444444")
        draw.text((width - 110, y), f"¥{amount:,}", font=_font(FONT_GOTHIC, 22), fill="#222222")
        y += 46

    y += 10
    draw.line([(30, y), (width - 30, y)], fill="#999999", width=2)
    y += 22
    tax = int(subtotal * 0.1)
    for label, value in (("小計", subtotal), ("消費税(10%)", tax), ("合計", subtotal + tax)):
        draw.text((40, y), label, font=_font(FONT_GOTHIC, 24), fill="#111111")
        draw.text((width - 180, y), f"¥{value:,}", font=_font(FONT_GOTHIC, 24), fill="#111111")
        y += 40
    draw.text((40, y), f"お預り  ¥{(subtotal + tax) // 1000 * 1000 + 1000:,}", font=_font(FONT_GOTHIC, 22), fill="#222222")
    y += 36
    draw.text((40, y), "上記正に領収いたしました", font=_font(FONT_GOTHIC, 20), fill="#333333")
    y += 34
    draw.text((40, y), "毎度ありがとうございました", font=_font(FONT_GOTHIC, 19), fill="#555555")
    return image


def render_invoice_a4(seed: int) -> Image.Image:
    """A4の領収書・請求書。名刺と違い、宛名と明細表がある。"""
    rng = random.Random(seed + 5000)
    shop, address, tel = rng.choice(SHOPS)
    items = rng.sample(ITEMS, k=rng.randint(4, 7))

    width, height = 1240, 1754  # A4 150dpi 相当
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)

    draw.text((width // 2 - 130, 110), "領 収 書", font=_font(FONT_GOTHIC, 56), fill="#111111")
    draw.text((100, 240), f"No. {rng.randint(10000, 99999)}", font=_font(FONT_LATIN, 24), fill="#333333")
    draw.text((900, 240), "2026年 7月 28日", font=_font(FONT_GOTHIC, 24), fill="#333333")

    draw.text((100, 330), "株式会社サンプル商事　御中", font=_font(FONT_GOTHIC, 34), fill="#111111")
    draw.line([(100, 385), (700, 385)], fill="#333333", width=2)

    subtotal = sum(price * rng.randint(1, 3) for _, price in items)
    tax = int(subtotal * 0.1)
    draw.text((100, 440), f"金 額  ¥{subtotal + tax:,} －", font=_font(FONT_GOTHIC, 44), fill="#111111")
    draw.text((100, 520), "但し　事務用品代として", font=_font(FONT_GOTHIC, 26), fill="#333333")
    draw.text((100, 566), "上記正に領収いたしました", font=_font(FONT_GOTHIC, 26), fill="#333333")

    y = 660
    draw.rectangle([100, y, width - 100, y + 46], fill="#eeeeee")
    for label, x in (("品名", 120), ("数量", 700), ("単価", 850), ("金額", 1030)):
        draw.text((x, y + 10), label, font=_font(FONT_GOTHIC, 24), fill="#111111")
    y += 46
    for name, price in items:
        qty = rng.randint(1, 3)
        draw.text((120, y + 8), name, font=_font(FONT_GOTHIC, 22), fill="#222222")
        draw.text((700, y + 8), str(qty), font=_font(FONT_GOTHIC, 22), fill="#222222")
        draw.text((850, y + 8), f"¥{price:,}", font=_font(FONT_GOTHIC, 22), fill="#222222")
        draw.text((1030, y + 8), f"¥{price * qty:,}", font=_font(FONT_GOTHIC, 22), fill="#222222")
        draw.line([(100, y + 44), (width - 100, y + 44)], fill="#cccccc")
        y += 46

    y += 20
    for label, value in (("小計", subtotal), ("消費税(10%)", tax), ("合計", subtotal + tax)):
        draw.text((850, y), label, font=_font(FONT_GOTHIC, 24), fill="#111111")
        draw.text((1030, y), f"¥{value:,}", font=_font(FONT_GOTHIC, 24), fill="#111111")
        y += 44

    y += 60
    draw.text((760, y), shop, font=_font(FONT_GOTHIC, 28), fill="#111111")
    draw.text((760, y + 44), address, font=_font(FONT_GOTHIC, 20), fill="#333333")
    draw.text((760, y + 76), f"TEL {tel}", font=_font(FONT_GOTHIC, 20), fill="#333333")
    draw.text((760, y + 108), f"登録番号 T{rng.randint(10**12, 10**13 - 1)}", font=_font(FONT_GOTHIC, 20), fill="#333333")
    return image


def build_mixed_folder(out: Path, *, receipts: int = 8, invoices: int = 4) -> list[tuple[str, str]]:
    """名刺と領収書が混在したフォルダを作る。戻り値は (ファイル名, 正解) の一覧。"""
    out.mkdir(parents=True, exist_ok=True)
    truth: list[tuple[str, str]] = []
    index = 0

    for sample in build_samples():
        index += 1
        name = f"scan_{index:03d}.jpg"
        sample.image.save(out / name, quality=92)
        truth.append((name, "business_card"))

    for seed in range(receipts):
        index += 1
        name = f"scan_{index:03d}.jpg"
        render_receipt_slip(seed).save(out / name, quality=92)
        truth.append((name, "receipt"))

    for seed in range(invoices):
        index += 1
        name = f"scan_{index:03d}.jpg"
        render_invoice_a4(seed).save(out / name, quality=92)
        truth.append((name, "receipt"))

    with (out / "_truth.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["file", "truth"])
        writer.writerows(truth)
    return truth


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, help="出力先フォルダ")
    parser.add_argument("--receipts", type=int, default=8)
    parser.add_argument("--invoices", type=int, default=4)
    args = parser.parse_args()

    truth = build_mixed_folder(Path(args.out), receipts=args.receipts, invoices=args.invoices)
    cards = sum(1 for _, label in truth if label == "business_card")
    print(f"{len(truth)} 件を生成しました（名刺 {cards} / 領収書 {len(truth) - cards}）: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
