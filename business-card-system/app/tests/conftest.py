"""テスト共通の準備。

環境変数は bcards.config の読み込み前に設定する必要があるため、
このファイルの先頭で設定する。
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix="bcards-test-"))
os.environ["BCARDS_DATABASE_URL"] = f"sqlite:///{TMP / 'test.db'}"
os.environ["BCARDS_STORAGE_DIR"] = str(TMP / "objects")
os.environ["BCARDS_SECRET_KEY"] = "test-secret"
os.environ["BCARDS_ENFORCE_IP_RESTRICTION"] = "0"
os.environ["BCARDS_OCR_PROVIDER"] = "mock"  # テストは外部・ローカルOCRに依存させない

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from bcards.db import SessionLocal, engine, init_db  # noqa: E402
from bcards.main import app  # noqa: E402
from bcards.models import ROLE_ADMIN, ROLE_MEMBER, Base, User  # noqa: E402
from bcards.security import hash_password  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_db():
    Base.metadata.drop_all(bind=engine)
    init_db()
    with SessionLocal() as db:
        db.add(
            User(
                login_id="admin",
                display_name="管理 太郎",
                email="admin@example.co.jp",
                role=ROLE_ADMIN,
                password_hash=hash_password("AdminPass123!"),
                external_access_allowed=True,
            )
        )
        db.add(
            User(
                login_id="member",
                display_name="一般 次郎",
                email="member@example.co.jp",
                role=ROLE_MEMBER,
                password_hash=hash_password("MemberPass123!"),
            )
        )
        db.commit()
    yield


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def login(client: TestClient, login_id: str = "member", password: str = "MemberPass123!"):
    response = client.post(
        "/login", data={"login_id": login_id, "password": password}, follow_redirects=False
    )
    assert response.status_code == 303, response.text
    return response


def csrf_of(client: TestClient) -> str:
    """画面に埋め込まれたCSRFトークンを取り出す。"""
    html = client.get("/cards/new").text
    marker = 'name="csrf_token" value="'
    start = html.index(marker) + len(marker)
    return html[start : html.index('"', start)]


def sample_card_image() -> bytes:
    """テスト用の名刺画像（実際の描画を伴う）。"""
    import io

    from PIL import Image, ImageDraw

    image = Image.new("RGB", (1000, 600), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle([20, 20, 980, 580], outline="#333333", width=3)
    draw.text((60, 60), "SAMPLE BUSINESS CARD", fill="#000000")
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=90)
    return buffer.getvalue()
