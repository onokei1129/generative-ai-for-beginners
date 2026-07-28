"""ラベル付けの進み具合の集計（poc/progress.py）。

測定に入る前の判断材料になるため、数え方が狂うと「終わったつもり」で
未確認のまま測ってしまう。そこだけを検証する。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from poc.progress import collect  # noqa: E402


def _image(path: Path) -> None:
    Image.new("RGB", (60, 40), "white").save(path)


def _label(path: Path, **fields) -> None:
    path.write_text(json.dumps(fields, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def cards(tmp_path: Path) -> Path:
    for i in range(1, 5):
        _image(tmp_path / f"card{i:02d}.jpg")
    return tmp_path


def test_counts_labeled_and_unlabeled(cards: Path):
    _label(cards / "card01.json", last_name="山田", company_name="A社")
    _label(cards / "card02.json", last_name="鈴木")

    result = collect(cards)

    assert len(result["images"]) == 4
    assert len(result["labeled"]) == 2
    assert {p.name for p in result["unlabeled"]} == {"card03.jpg", "card04.jpg"}


def test_unverified_fields_are_reported(cards: Path):
    """未確認のまま測ると精度が実際より良く出るため、必ず拾えること。"""
    _label(cards / "card01.json", last_name="山田", _unverified=["email", "tel"])
    _label(cards / "card02.json", last_name="鈴木")

    result = collect(cards)

    assert result["unverified"] == {"card01.jpg": ["email", "tel"]}


def test_label_with_no_values_is_flagged_as_empty(cards: Path):
    """全項目が空＝名刺でない可能性。未入力とは区別する。"""
    _label(cards / "card01.json")
    _label(cards / "card02.json", last_name="鈴木")

    result = collect(cards)

    assert [p.name for p in result["empty"]] == ["card01.jpg"]
    assert len(result["labeled"]) == 2  # 空でもラベル済みには数える


def test_broken_label_file_does_not_crash(cards: Path):
    (cards / "card01.json").write_text("{壊れたJSON", encoding="utf-8")

    result = collect(cards)

    assert "card01.jpg" in result["unverified"]


def test_non_image_files_are_ignored(cards: Path):
    (cards / "sort.csv").write_text("a,b\n", encoding="utf-8")
    (cards / "memo.txt").write_text("hello", encoding="utf-8")
    (cards / "unknown").mkdir()
    _image(cards / "unknown" / "maybe.jpg")

    result = collect(cards)

    # サブフォルダ（unknown）の画像は対象に含めない
    assert len(result["images"]) == 4
