"""本番相当のデータ量で見つかった性能問題の回帰テスト。

実測（名刺1万件・画像3万件）で次の2点が見つかった。どちらも件数に比例して悪化する。

1. ホーム画面が表示のたびにストレージ全体を走査していた（490ms）
2. CSV出力が名刺1件ごとに連絡先を読み直していた（N+1。1万件で12秒）

いずれも「遅い」ことをそのまま計測するとテストが不安定になるため、
**発行されるクエリ数と、集計が呼ばれた回数**で検証する。
"""

from __future__ import annotations

from conftest import csrf_of, login, sample_card_image

from sqlalchemy import event

from bcards.db import SessionLocal, engine
from bcards.models import BusinessCard, CardContact, Company, Person
from bcards.services import storage
from bcards.services.ocr.parser import normalize_company, normalize_name


class QueryCounter:
    """with ブロックの中で発行されたSQL文を数える。"""

    def __init__(self) -> None:
        self.statements: list[str] = []

    def __enter__(self):
        event.listen(engine, "before_cursor_execute", self._record)
        return self

    def __exit__(self, *exc):
        event.remove(engine, "before_cursor_execute", self._record)

    def _record(self, conn, cursor, statement, parameters, context, executemany):
        self.statements.append(statement)

    def count(self, keyword: str) -> int:
        return sum(1 for s in self.statements if keyword in s)


def _make_cards(count: int) -> None:
    with SessionLocal() as db:
        company = Company(name="株式会社テスト", name_normalized=normalize_company("株式会社テスト"))
        db.add(company)
        db.flush()
        for index in range(count):
            person = Person(
                last_name="山田",
                first_name=f"太郎{index}",
                full_name_normalized=normalize_name(f"山田太郎{index}"),
            )
            db.add(person)
            db.flush()
            card = BusinessCard(
                person_id=person.person_id,
                company_id=company.company_id,
                company_name_raw="株式会社テスト",
                is_latest=True,
            )
            db.add(card)
            db.flush()
            for contact_type, value in (("tel", f"03-1234-{index:04d}"), ("email", f"u{index}@example.jp")):
                db.add(
                    CardContact(
                        card_id=card.card_id,
                        contact_type=contact_type,
                        value_raw=value,
                        value_normalized=value.lower(),
                    )
                )
        db.commit()


def test_csv_export_does_not_query_contacts_per_card(client):
    """連絡先はまとめて読む。名刺の件数を増やしてもクエリ数が増えないこと。"""
    login(client, "admin", "AdminPass123!")
    token = csrf_of(client)
    _make_cards(20)

    with QueryCounter() as counter:
        response = client.post(
            "/export",
            data={
                "csrf_token": token,
                "scope": "all",
                "confirmed": "1",
                "columns": ["person_name", "company_name", "tel", "email"],
            },
        )
    assert response.status_code == 200
    assert len(response.text.strip().splitlines()) >= 20

    contact_queries = counter.count("FROM card_contact")
    # まとめ読みなら1〜2回。1件ずつ読んでいると名刺の件数だけ発行される
    assert contact_queries <= 3, f"card_contact へのクエリが {contact_queries} 回発行されています（N+1）"


def test_storage_usage_is_cached_between_page_loads(client, monkeypatch):
    """ホーム画面を何度開いてもストレージ集計は1回しか走らないこと。"""
    from bcards.config import settings

    monkeypatch.setattr(settings, "storage_usage_cache_seconds", 300.0)
    storage.invalidate_usage_cache()

    calls = {"count": 0}
    real = storage.get_backend().total_bytes

    def counting_total_bytes():
        calls["count"] += 1
        return real()

    monkeypatch.setattr(storage.get_backend(), "total_bytes", counting_total_bytes)

    login(client)
    for _ in range(5):
        assert client.get("/").status_code == 200

    assert calls["count"] == 1, f"ストレージ集計が {calls['count']} 回走っています（キャッシュが効いていない）"


def test_fresh_flag_recomputes_storage_usage(monkeypatch):
    from bcards.config import settings

    monkeypatch.setattr(settings, "storage_usage_cache_seconds", 300.0)
    storage.invalidate_usage_cache()

    calls = {"count": 0}
    real = storage.get_backend().total_bytes

    def counting_total_bytes():
        calls["count"] += 1
        return real()

    monkeypatch.setattr(storage.get_backend(), "total_bytes", counting_total_bytes)

    storage.total_bytes()
    storage.total_bytes()
    assert calls["count"] == 1
    storage.total_bytes(fresh=True)
    assert calls["count"] == 2


def test_cache_can_be_disabled(monkeypatch):
    """0を指定したら毎回集計する（設定が効くことの確認）。"""
    from bcards.config import settings

    monkeypatch.setattr(settings, "storage_usage_cache_seconds", 0.0)
    storage.invalidate_usage_cache()

    calls = {"count": 0}
    real = storage.get_backend().total_bytes
    monkeypatch.setattr(
        storage.get_backend(), "total_bytes", lambda: (calls.__setitem__("count", calls["count"] + 1), real())[1]
    )

    storage.total_bytes()
    storage.total_bytes()
    assert calls["count"] == 2


def test_new_upload_is_reflected_after_cache_expires(client, monkeypatch):
    """キャッシュ期限内は古い値でよいが、期限が切れれば増分が反映されること。"""
    from bcards.config import settings

    monkeypatch.setattr(settings, "storage_usage_cache_seconds", 300.0)
    storage.invalidate_usage_cache()
    before = storage.total_bytes()

    storage.put_bytes(sample_card_image(), suffix=".jpg", prefix="cards/test")
    assert storage.total_bytes() == before  # キャッシュ期限内は変わらない

    monkeypatch.setattr(settings, "storage_usage_cache_seconds", 0.0)
    assert storage.total_bytes() > before
