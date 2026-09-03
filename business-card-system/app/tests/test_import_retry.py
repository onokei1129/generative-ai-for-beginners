"""取込の再処理（キューファイル単位）に関する回帰テスト。

OCR中はDBトランザクションを閉じているため（services/importer.py 参照）、
途中で落ちた場合は作りかけの明細がDBに残る。再処理でそれが二重にならないことを確認する。
"""

from __future__ import annotations

from conftest import csrf_of, drain_queue, login, sample_card_image

from bcards.db import SessionLocal
from bcards.models import CardImage, ImportFile, ImportItem, OcrResult
from bcards.services import importer


def _upload(client) -> None:
    token = csrf_of(client)
    response = client.post(
        "/imports/upload",
        data={"csrf_token": token, "source": "file_upload"},
        files={"files": ("card.jpg", sample_card_image(), "image/jpeg")},
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_item_records_its_source_file(client):
    login(client)
    _upload(client)
    assert drain_queue() == 1

    with SessionLocal() as db:
        item = db.query(ImportItem).one()
        import_file = db.query(ImportFile).one()
        assert item.import_file_id == import_file.import_file_id


def test_reprocessing_a_file_does_not_duplicate_items(client):
    """1回目の途中で落ちた想定でキューへ戻し、明細が1件のままであることを確認する。"""
    login(client)
    _upload(client)
    assert drain_queue() == 1

    with SessionLocal() as db:
        import_file = db.query(ImportFile).one()
        # ワーカーが落ちて requeue_stale で戻された状態を再現する
        import_file.status = "queued"
        import_file.finished_at = None
        db.commit()

    assert drain_queue() == 1

    with SessionLocal() as db:
        assert db.query(ImportItem).count() == 1
        assert db.query(OcrResult).count() == 1
        item = db.query(ImportItem).one()
        assert item.status == "pending_review"
        assert db.query(ImportFile).one().attempts == 2


def test_discard_keeps_already_registered_items(client):
    """登録済みの明細は再処理でも消さない（名刺本体から参照されているため）。"""
    login(client)
    token = csrf_of(client)
    _upload(client)
    drain_queue()

    with SessionLocal() as db:
        item_id = db.query(ImportItem).one().import_item_id
    response = client.post(
        f"/imports/items/{item_id}/register",
        data={
            "csrf_token": token,
            "action": "new_person",
            "last_name": "山田",
            "first_name": "太郎",
            "company_name": "株式会社サンプル商事",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    with SessionLocal() as db:
        assert db.query(ImportItem).one().card_id is not None
        file_id = db.query(ImportFile).one().import_file_id
        assert importer.discard_items_of_file(db, file_id) == 0
        assert db.query(ImportItem).count() == 1
        assert db.query(CardImage).count() > 0
