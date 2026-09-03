"""本番相当のデータ量を投入して、性能と所要時間を実測するための検証用ツール。

    # 1万件の名刺データ（画像つき）を投入する
    PYTHONPATH=src .venv/bin/python ops/loadgen.py --cards 10000

    # 画像を作らずDBだけ（検索性能の測定用。高速）
    PYTHONPATH=src .venv/bin/python ops/loadgen.py --cards 10000 --no-images

用途:

- **RTO の確定**（論点O）：本番相当のデータでバックアップ・復元の所要時間を測る
- **検索応答時間**（非機能要件「1万件規模で2秒以内」）の確認

投入するのは架空のデータです。**本番環境では絶対に実行しないでください。**
`BCARDS_ENV=production` のときは実行を拒否します。
"""

from __future__ import annotations

import argparse
import random
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PIL import Image, ImageDraw  # noqa: E402

from bcards import fonts  # noqa: E402
from bcards.config import settings  # noqa: E402
from bcards.db import SessionLocal  # noqa: E402
from bcards.models import (  # noqa: E402
    BusinessCard,
    CardContact,
    CardImage,
    Company,
    Person,
    User,
    utcnow,
)
from bcards.services import storage  # noqa: E402
from bcards.services.images import make_variants  # noqa: E402
from bcards.services.ocr.parser import normalize_company, normalize_name, normalize_phone  # noqa: E402

SURNAMES = [
    ("佐藤", "さとう"), ("鈴木", "すずき"), ("高橋", "たかはし"), ("田中", "たなか"),
    ("伊藤", "いとう"), ("渡辺", "わたなべ"), ("山本", "やまもと"), ("中村", "なかむら"),
    ("小林", "こばやし"), ("加藤", "かとう"), ("吉田", "よしだ"), ("山田", "やまだ"),
    ("佐々木", "ささき"), ("山口", "やまぐち"), ("松本", "まつもと"), ("井上", "いのうえ"),
]
GIVEN_NAMES = [
    ("太郎", "たろう"), ("次郎", "じろう"), ("花子", "はなこ"), ("一郎", "いちろう"),
    ("美咲", "みさき"), ("健太", "けんた"), ("由美", "ゆみ"), ("翔太", "しょうた"),
    ("愛", "あい"), ("大輔", "だいすけ"), ("恵子", "けいこ"), ("拓也", "たくや"),
]
COMPANY_STEMS = [
    "サンプル商事", "テクノロジー", "みらいデザイン", "北海道フーズ", "関西システムズ",
    "東京インダストリー", "九州ロジスティクス", "中部エンジニアリング", "信越マテリアル",
    "四国トレーディング", "東北ソリューション", "北陸メタル", "沖縄リゾート開発",
]
COMPANY_FORMS = ["株式会社", "有限会社", "合同会社"]
DEPARTMENTS = ["営業本部", "第一営業部", "開発部", "総務部", "経理部", "人事部", "情報システム部", "海外事業部"]
TITLES = ["代表取締役", "取締役", "本部長", "部長", "次長", "課長", "係長", "主任", "エンジニア", ""]
PREFECTURES = [
    ("100-0001", "東京都千代田区千代田1-1-1", "03"),
    ("530-0001", "大阪府大阪市北区梅田2-2-2", "06"),
    ("460-0008", "愛知県名古屋市中区栄3-3-3", "052"),
    ("060-0001", "北海道札幌市中央区北一条西4-4-4", "011"),
    ("810-0001", "福岡県福岡市中央区天神5-5-5", "092"),
    ("980-0021", "宮城県仙台市青葉区中央6-6-6", "022"),
]


def _person_fields(rng: random.Random, index: int) -> dict:
    last, last_kana = rng.choice(SURNAMES)
    first, first_kana = rng.choice(GIVEN_NAMES)
    stem = rng.choice(COMPANY_STEMS)
    form = rng.choice(COMPANY_FORMS)
    postal, address, area = rng.choice(PREFECTURES)
    # index を混ぜて、同姓同名・同社名が現実的な割合で出るようにする
    company = f"{form}{stem}" if index % 7 else f"{form}{stem}{index // 7}"
    return {
        "last_name": last,
        "first_name": first,
        "last_name_kana": last_kana,
        "first_name_kana": first_kana,
        "company_name": company,
        "department_name": rng.choice(DEPARTMENTS),
        "title": rng.choice(TITLES),
        "postal_code": postal,
        "address": address,
        "tel": f"{area}-{rng.randint(1000, 9999)}-{rng.randint(1000, 9999)}",
        "mobile": f"090-{rng.randint(1000, 9999)}-{rng.randint(1000, 9999)}",
        "email": f"user{index:05d}@example.co.jp",
        "url": f"https://www.example{index % 50}.co.jp",
    }


def _render(fields: dict, index: int) -> Image.Image:
    """名刺画像を1枚描く。内容が毎回違うので、内容ハッシュも重複しない。"""
    image = Image.new("RGB", (1050, 630), "white")
    draw = ImageDraw.Draw(image)
    font = fonts.load  # 環境ごとに実在するフォントを使う

    draw.rectangle([0, 0, 12, image.height], fill="#1f5fa9")
    draw.text((70, 60), fields["company_name"], font=font(40), fill="#111111")
    draw.text((70, 130), fields["department_name"], font=font(24), fill="#333333")
    draw.text((70, 170), fields["title"], font=font(24), fill="#333333")
    draw.text((70, 230), f"{fields['last_name_kana']} {fields['first_name_kana']}", font=font(22), fill="#666666")
    draw.text((70, 270), f"{fields['last_name']} {fields['first_name']}", font=font(52), fill="#111111")
    draw.text((70, 370), f"〒{fields['postal_code']} {fields['address']}", font=font(22), fill="#222222")
    draw.text((70, 410), f"TEL {fields['tel']}", font=font(22), fill="#222222")
    draw.text((70, 445), f"Mobile {fields['mobile']}", font=font(22), fill="#222222")
    draw.text((70, 480), fields["email"], font=font(22), fill="#222222")
    draw.text((70, 515), fields["url"], font=font(22), fill="#222222")
    # 1枚ごとに異なるノイズを入れ、JPEG のサイズが実物に近くなるようにする
    rng = random.Random(index)
    for _ in range(400):
        x, y = rng.randint(0, 1049), rng.randint(0, 629)
        draw.point((x, y), fill=(rng.randint(200, 255),) * 3)
    return image


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cards", type=int, default=1000, help="投入する名刺の件数")
    parser.add_argument("--no-images", action="store_true", help="画像を作らない（DBだけ／高速）")
    parser.add_argument("--batch", type=int, default=200, help="コミット単位")
    parser.add_argument("--seed", type=int, default=20260728)
    args = parser.parse_args()

    if settings.env == "production":
        print("BCARDS_ENV=production では実行できません（架空データの投入ツールです）。", file=sys.stderr)
        return 2

    rng = random.Random(args.seed)
    started = time.time()
    base_date = utcnow() - timedelta(days=365)

    with SessionLocal() as db:
        user = db.query(User).first()
        if user is None:
            print("利用者が1人もいません。先に seed.py を実行してください。", file=sys.stderr)
            return 2
        companies: dict[str, Company] = {}
        created = 0

        for index in range(args.cards):
            fields = _person_fields(rng, index)

            normalized = normalize_company(fields["company_name"])
            company = companies.get(normalized)
            if company is None:
                company = (
                    db.query(Company).filter(Company.name_normalized == normalized).first()
                )
                if company is None:
                    company = Company(
                        name=fields["company_name"],
                        name_normalized=normalized,
                        postal_code=fields["postal_code"],
                        address=fields["address"],
                        created_by=user.user_id,
                        updated_by=user.user_id,
                    )
                    db.add(company)
                    db.flush()
                companies[normalized] = company

            person = Person(
                last_name=fields["last_name"],
                first_name=fields["first_name"],
                last_name_kana=fields["last_name_kana"],
                first_name_kana=fields["first_name_kana"],
                full_name_normalized=normalize_name(f"{fields['last_name']}{fields['first_name']}"),
                created_by=user.user_id,
                updated_by=user.user_id,
            )
            db.add(person)
            db.flush()

            card = BusinessCard(
                person_id=person.person_id,
                company_id=company.company_id,
                company_name_raw=fields["company_name"],
                department_name=fields["department_name"],
                title=fields["title"],
                postal_code=fields["postal_code"],
                address=fields["address"],
                exchanged_on=base_date + timedelta(days=rng.randint(0, 364)),
                exchanged_by_user_id=user.user_id,
                is_latest=True,
                source="scan",
                created_by=user.user_id,
                updated_by=user.user_id,
            )
            db.add(card)
            db.flush()
            person.latest_card_id = card.card_id

            for key, contact_type in (("tel", "tel"), ("mobile", "mobile"), ("email", "email"), ("url", "url")):
                raw = fields[key]
                db.add(
                    CardContact(
                        card_id=card.card_id,
                        contact_type=contact_type,
                        value_raw=raw,
                        value_normalized=(
                            normalize_phone(raw) if contact_type in ("tel", "mobile", "fax") else raw.lower()
                        ),
                    )
                )

            if not args.no_images:
                image = _render(fields, index)
                for variant, (payload, rendered) in make_variants(image).items():
                    key = storage.put_bytes(payload, suffix=".jpg", prefix=f"cards/{variant}")
                    db.add(
                        CardImage(
                            card_id=card.card_id,
                            side="front",
                            variant=variant,
                            storage_key=key,
                            mime_type="image/jpeg",
                            width=rendered.width,
                            height=rendered.height,
                            byte_size=len(payload),
                            checksum=storage.checksum(payload),
                        )
                    )

            created += 1
            if created % args.batch == 0:
                db.commit()
                elapsed = time.time() - started
                rate = created / elapsed
                remaining = (args.cards - created) / rate if rate else 0
                print(
                    f"  {created}/{args.cards} 件 "
                    f"({rate:.0f} 件/秒, 残り約 {remaining / 60:.1f} 分)",
                    flush=True,
                )
        db.commit()

    elapsed = time.time() - started
    print(f"\n{created} 件を投入しました（{elapsed:.0f} 秒 / {created / elapsed:.0f} 件/秒）")
    if not args.no_images:
        total = storage.total_bytes()
        print(f"ストレージ使用量: {total / 1024 ** 3:.2f} GB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
