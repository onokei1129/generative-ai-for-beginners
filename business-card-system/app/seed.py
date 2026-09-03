"""初期データ投入と動作確認用のデモデータ生成。

    python seed.py                # 管理者・一般利用者アカウントのみ作成
    python seed.py --demo         # デモ用の名刺画像を生成し、取込〜登録まで実行
    python seed.py --demo --count 12
"""

from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from bcards import fonts  # noqa: E402
from bcards.db import SessionLocal, init_db  # noqa: E402
from bcards.models import (  # noqa: E402
    ROLE_ADMIN,
    ROLE_MEMBER,
    AllowedIp,
    User,
)
from bcards.security import hash_password  # noqa: E402


DEMO_PEOPLE = [
    ("株式会社サンプル商事", "営業本部 第一営業部", "部長", "山田", "太郎", "やまだ", "たろう",
     "100-0001", "東京都千代田区千代田1-1-1", "03-1234-5678", "090-1234-5678", "03-1234-5679",
     "taro.yamada@example.co.jp", "https://www.example.co.jp"),
    ("テクノロジー株式会社", "開発部", "シニアエンジニア", "佐藤", "花子", "さとう", "はなこ",
     "530-0001", "大阪府大阪市北区梅田2-2-2", "06-9876-5432", "080-2222-3333", "",
     "hanako.sato@example.jp", "https://tech.example.jp"),
    ("合同会社みらいデザイン", "クリエイティブ室", "代表社員", "鈴木", "一郎", "すずき", "いちろう",
     "460-0008", "愛知県名古屋市中区栄3-3-3", "052-111-2222", "", "052-111-2223",
     "ichiro@mirai.example", ""),
    ("株式会社ロジスティクス九州", "物流企画部", "課長", "田中", "健二", "たなか", "けんじ",
     "812-0011", "福岡県福岡市博多区博多駅前4-4-4", "092-333-4444", "070-4444-5555", "",
     "tanaka@logi-kyushu.example", "https://logi-kyushu.example"),
    ("北海道フーズ株式会社", "商品開発部", "主任", "高橋", "美咲", "たかはし", "みさき",
     "060-0001", "北海道札幌市中央区北一条西5-5-5", "011-555-6666", "090-6666-7777", "",
     "takahashi@hokkaido-foods.example", ""),
    ("株式会社サンプル商事", "経営企画部", "取締役", "山田", "太郎", "やまだ", "たろう",
     "100-0001", "東京都千代田区千代田1-1-1", "03-1234-5600", "090-1234-5678", "",
     "taro.yamada@example.co.jp", "https://www.example.co.jp"),
]


def create_users(db) -> None:
    accounts = [
        ("admin", "管理 太郎", "admin@example.co.jp", ROLE_ADMIN, "AdminPass123!"),
        ("sato", "佐藤 次郎", "sato@example.co.jp", ROLE_MEMBER, "MemberPass123!"),
        ("suzuki", "鈴木 三郎", "suzuki@example.co.jp", ROLE_MEMBER, "MemberPass123!"),
    ]
    for login_id, name, email, role, password in accounts:
        if db.query(User).filter(User.login_id == login_id).first():
            continue
        db.add(
            User(
                login_id=login_id,
                display_name=name,
                email=email,
                role=role,
                password_hash=hash_password(password),
                external_access_allowed=(role == ROLE_ADMIN),
            )
        )
        print(f"利用者を作成: {login_id} / {password}")
    db.commit()


def ensure_local_ip(db) -> None:
    """開発環境からアクセスできるよう、ループバックと私設アドレスを許可しておく。"""
    if db.query(AllowedIp).count():
        return
    for cidr, label in (("127.0.0.0/8", "ローカル"), ("10.0.0.0/8", "社内LAN(例)"), ("192.168.0.0/16", "社内LAN(例)")):
        db.add(AllowedIp(cidr=cidr, label=label))
    db.commit()
    print("許可IPの初期値を登録しました（本番では自社の拠点IPに置き換えてください）。")


def render_card_image(entry: tuple, *, tilt: float = 0.0) -> bytes:
    """デモ用の名刺画像を生成する（実際のスキャン画像の代わり）。"""
    (company, department, title, last, first, last_kana, first_kana,
     postal, address, tel, mobile, fax, email, url) = entry

    width, height = 1050, 630
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)

    def font(size: int) -> ImageFont.FreeTypeFont:
        return fonts.load(size)

    draw.rectangle([0, 0, width - 1, height - 1], outline="#dddddd", width=2)
    draw.rectangle([0, 0, 12, height], fill="#1f5fa9")

    y = 60
    draw.text((70, y), company, font=font(40), fill="#111111")
    y += 60
    draw.text((70, y), department, font=font(26), fill="#333333")
    y += 40
    draw.text((70, y), title, font=font(26), fill="#333333")
    y += 55
    draw.text((70, y), f"{last_kana} {first_kana}", font=font(22), fill="#666666")
    y += 34
    draw.text((70, y), f"{last} {first}", font=font(52), fill="#111111")

    y = 430
    draw.text((70, y), f"〒{postal} {address}", font=font(22), fill="#222222")
    y += 34
    contacts = f"TEL {tel}"
    if fax:
        contacts += f"  FAX {fax}"
    draw.text((70, y), contacts, font=font(22), fill="#222222")
    y += 34
    if mobile:
        draw.text((70, y), f"Mobile {mobile}", font=font(22), fill="#222222")
        y += 34
    draw.text((70, y), email + (f"  {url}" if url else ""), font=font(22), fill="#222222")

    if tilt:
        image = image.rotate(tilt, expand=True, fillcolor=(235, 235, 235), resample=Image.BICUBIC)

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=92)
    return buffer.getvalue()


def create_demo_cards(db, count: int) -> None:
    """デモ画像を取込パイプラインに通し、確認済みとして登録する。"""
    from types import SimpleNamespace

    from bcards.services.cards import register_card
    from bcards.services.importer import create_job, latest_ocr, process_job
    from bcards.models import ITEM_REVIEW, CardImage, ImportItem

    admin = db.query(User).filter(User.login_id == "admin").first()
    request = SimpleNamespace(
        headers={"user-agent": "seed-script"},
        cookies={},
        client=SimpleNamespace(host="127.0.0.1"),
        state=SimpleNamespace(),
    )

    files = []
    for index in range(count):
        entry = DEMO_PEOPLE[index % len(DEMO_PEOPLE)]
        tilt = [0, 2.5, -3.0][index % 3]
        files.append((f"demo_{index + 1:02d}.jpg", render_card_image(entry, tilt=tilt)))

    job = create_job(db, admin, files)
    db.commit()
    process_job(db, job, files, source="scan")
    db.commit()

    registered = 0
    for item in db.query(ImportItem).filter(ImportItem.import_job_id == job.import_job_id).all():
        if item.status != ITEM_REVIEW:
            print(f"  スキップ: {item.source_file_name} ({item.status}) {item.error_message or ''}")
            continue
        ocr = latest_ocr(db, item)
        fields = dict(ocr.extracted_fields or {})
        from bcards.services.dedupe import find_candidates

        candidates = [c.as_dict() for c in find_candidates(db, fields)]
        action = "keep_history" if candidates else "new_person"
        image_ids = [
            img.card_image_id
            for img in db.query(CardImage).filter(CardImage.import_item_id == item.import_item_id).all()
        ]
        card = register_card(
            db, request, admin,
            fields=fields,
            action=action,
            person_id=candidates[0]["person_id"] if candidates else None,
            image_ids=image_ids,
            source="scan",
            reason="デモデータ投入",
        )
        item.status = "registered"
        item.card_id = card.card_id
        item.chosen_action = action
        registered += 1
    db.commit()
    print(f"デモ名刺を {registered} 件登録しました（OCR→確認→登録の流れを実行）。")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", action="store_true", help="デモ用の名刺データを生成する")
    parser.add_argument("--count", type=int, default=6, help="生成するデモ名刺の枚数")
    args = parser.parse_args()

    init_db()
    with SessionLocal() as db:
        create_users(db)
        ensure_local_ip(db)
        if args.demo:
            create_demo_cards(db, args.count)
    print("完了しました。 http://127.0.0.1:8000/ にアクセスしてください。")


if __name__ == "__main__":
    main()
