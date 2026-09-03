"""90度単位の向き補正（services/orientation.py）。

読み取り機に横向きに置いた名刺が、画像ごと90度回った状態で入ってくることがある。
実測ではこの1枚から取れる項目が 14項目 → 2項目 まで落ちた。人が見れば読めるため
気づきにくく、「OCRが弱い」と誤解されやすい種類の不具合。

ここで固定するのは2点。

1. 回るべきときに、正しい向きへ回すこと
2. **回るべきでないときに回さないこと**（縦書き名刺・確信度の低い判定・向き検出データが無い環境）

2 のほうが重い。誤って回すと、それまで読めていた名刺が読めなくなる。
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from bcards.services import orientation  # noqa: E402

HAS_TESSERACT = shutil.which("tesseract") is not None


def _osd(monkeypatch, *, rotate: int, conf: float) -> None:
    """pytesseract の向き検出を差し替える（CIには tesseract が無いため）。"""
    import pytesseract

    monkeypatch.setattr(
        pytesseract,
        "image_to_osd",
        lambda *a, **k: {"rotate": rotate, "orientation_conf": conf},
    )


def _marked(width: int, height: int) -> Image.Image:
    """左上だけ赤い画像。回転の向きを目で追えるようにする。"""
    image = Image.new("RGB", (width, height), "white")
    image.putpixel((0, 0), (255, 0, 0))
    return image


def _red_corner(image: Image.Image) -> tuple[int, int]:
    for y in range(image.height):
        for x in range(image.width):
            if image.getpixel((x, y))[0] > 200 and image.getpixel((x, y))[1] < 80:
                return x, y
    raise AssertionError("目印が消えている")


class TestRotatesWhenNeeded:
    def test_rotation_is_clockwise(self, monkeypatch):
        """OSDの「この角度だけ時計回りに回すと正立する」に合わせること。

        符号を取り違えると180度ずれた向きになり、症状が直らないどころか
        正立していた名刺まで壊れる。
        """
        _osd(monkeypatch, rotate=90, conf=8.0)
        source = _marked(100, 50)

        result, degrees = orientation.upright(source)

        assert degrees == 90
        assert (result.width, result.height) == (50, 100)
        # 時計回りなら、左上の目印は右上へ移る
        x, y = _red_corner(result)
        assert (x, y) == (result.width - 1, 0)

    @pytest.mark.parametrize("degrees", [90, 180, 270])
    def test_reported_angle_is_recorded(self, monkeypatch, degrees: int):
        _osd(monkeypatch, rotate=degrees, conf=8.0)

        _, applied = orientation.upright(_marked(100, 50))

        assert applied == degrees


def _osd_varies(monkeypatch, *, big: tuple, small: tuple) -> None:
    """画像の大きさで答えが変わる向き検出を作る。

    判定は長辺1600と1100の2つの大きさで見る。その2つで答えが割れる状況を
    作るために、渡された画像の大きさで返す値を変える。
    """
    import pytesseract

    def answer(image, *args, **kwargs):
        rotate, conf = big if max(image.size) >= 1400 else small
        return {"rotate": rotate, "orientation_conf": conf}

    monkeypatch.setattr(pytesseract, "image_to_osd", answer)


class TestDoesNotRotateWhenUnsure:
    """誤って回す害のほうが大きいので、迷ったら回さない。

    ただし「迷った」の測り方を、1回の確信度から**大きさを変えても答えが
    同じか**に改めた。実テスト25枚目（431x706 の小さい取り込み）で、
    正しい答え 270度 が確信度 0.87 で見送られていた。大きさを変えて見ると
    確信度は 0.87〜2.66 と下限（2.0）の周りで揺れるのに、**角度はどの
    大きさでも 270 のまま**だった。1回の確信度より、答えが大きさに依らない
    ことのほうが確かな手がかりになる。

    誤って回す害への歯止めは残っている——**答えが割れたら回さない**。
    """

    def test_a_split_answer_is_not_used(self, monkeypatch):
        """確信度が足りず、大きさを変えると答えも変わるなら、回さない。"""
        _osd_varies(
            monkeypatch,
            big=(90, orientation.MIN_CONFIDENCE - 0.1),
            small=(180, orientation.MIN_CONFIDENCE - 0.1),
        )
        source = _marked(100, 50)

        result, degrees = orientation.upright(source)

        assert degrees == 0
        assert (result.width, result.height) == (100, 50)

    def test_the_same_answer_twice_is_used(self, monkeypatch):
        """確信度が足りなくても、大きさを変えて同じ答えなら回す（25枚目）。"""
        _osd_varies(
            monkeypatch,
            big=(90, orientation.MIN_CONFIDENCE - 0.1),
            small=(90, orientation.MIN_CONFIDENCE - 0.5),
        )
        source = _marked(100, 50)

        result, degrees = orientation.upright(source)

        assert degrees == 90
        assert (result.width, result.height) == (50, 100)

    def test_zero_rotation_leaves_image_untouched(self, monkeypatch):
        """縦書き名刺はここに入る（OSDは縦書きを正立と判定する）。"""
        _osd(monkeypatch, rotate=0, conf=10.0)
        source = _marked(50, 100)

        result, degrees = orientation.upright(source)

        assert degrees == 0
        assert result is source

    def test_missing_osd_data_does_not_stop_ocr(self, monkeypatch):
        """向き検出用データ(osd)が無い環境でも、取込を止めないこと。"""
        import pytesseract

        def _boom(*args, **kwargs):
            raise pytesseract.TesseractError(1, "Error: osd.traineddata not found")

        monkeypatch.setattr(pytesseract, "image_to_osd", _boom)

        result, degrees = orientation.upright(_marked(100, 50))

        assert degrees == 0
        assert result.size == (100, 50)

    def test_unexpected_angle_is_ignored(self, monkeypatch):
        """90度の倍数以外は判定失敗とみなす。"""
        _osd(monkeypatch, rotate=45, conf=10.0)

        _, degrees = orientation.upright(_marked(100, 50))

        assert degrees == 0


@pytest.fixture(scope="module")
def sample():
    from poc.samples import build_samples

    return next(s for s in build_samples() if s.variant == "standard/scan")


@pytest.mark.skipif(not HAS_TESSERACT, reason="tesseract が無い環境ではOCRの実測を行わない")
class TestAgainstRealOcr:
    """実際に tesseract を通して、症状が再現しないことを確かめる。"""

    def _extract(self, image: Image.Image) -> int:
        import io

        from bcards.services import images as image_service
        from bcards.services.ocr.parser import parse_fields
        from bcards.services.ocr.providers import TesseractOcrProvider

        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, format="JPEG", quality=95)
        card = image_service.process_file(buffer.getvalue(), "sample.jpg", correct=True)[0]
        output = TesseractOcrProvider().recognize(card.ocr_image)
        fields = parse_fields(output.lines or output.text.splitlines())["fields"]
        return sum(1 for value in fields.values() if str(value or "").strip())

    @pytest.mark.parametrize("turned", [90, 180, 270])
    def test_rotated_card_recovers_its_fields(self, sample, turned: int):
        """回転前と同じだけ項目が取れること（補正前は 14項目 → 2項目 だった）。"""
        upright_count = self._extract(sample.image)
        rotated_count = self._extract(sample.image.rotate(turned, expand=True))

        assert upright_count >= 12, "前提が崩れている（正立でも読めていない）"
        assert rotated_count >= upright_count - 1

    def test_vertical_card_is_not_damaged(self):
        """縦書き名刺を巻き添えにしないこと。形だけで回すと壊れる。"""
        from poc.samples import build_samples

        vertical = next(s for s in build_samples() if s.variant == "vertical/scan")

        assert self._extract(vertical.image) >= 6
