"""LLM項目分離アダプタの契約テスト。

Claude API の認証情報が無い環境でも、SDKに実際に渡すリクエストの形と
応答の解釈を検証できるよう、HTTPトランスポートだけを差し替えて確認する。
（モデルの応答品質そのものは実測 PoC 側で測る）
"""

from __future__ import annotations

import json

import pytest
from PIL import Image

from bcards.services.ocr import extract_fields
from bcards.services.ocr.base import OcrOutput
from bcards.services.ocr.llm_extractor import ExtractedCardFields, LlmFieldExtractor

# SDKに渡す模擬トランスポートは、**そのSDKが使っている httpx** で作ること。
#
# anthropic 1.x は HTTP層を httpx から、その維持されている分家 httpx2 へ移した。
# 古いほうの `httpx.Client` を渡すと、組み立てた時点で TypeError になる
# （`Expected an instance of httpx2.Client`）。CI は requirements の
# `anthropic>=0.60` から新しいほうを取ってくるので、手元が 0.x のままでも
# CI だけが落ちる。実際にそうなった。
#
# 本体（llm_extractor.py）は自前の HTTP を持たないので影響を受けない。
# 壊れるのはこの模擬だけである。どちらの版でも動くよう、SDKが使っている
# ほうに合わせて取り込む。
try:  # anthropic 1.x
    import httpx2 as httpx
except ImportError:  # anthropic 0.x
    import httpx

OCR_TEXT = "株式会社サンプル商事\n営業本部\n山田 太郎\nTEL 03-1234-5678"

ANSWER = {
    "last_name": "山田",
    "first_name": "太郎",
    "last_name_kana": "やまだ",
    "first_name_kana": "たろう",
    "company_name": "株式会社サンプル商事",
    "department_name": "営業本部",
    "title": "部長",
    "postal_code": "100-0001",
    "address": "東京都千代田区千代田1-1-1",
    "tel": "03-1234-5678",
    "mobile": "",
    "fax": "",
    "email": "taro@example.co.jp",
    "url": "",
    "note": "",
}


def _client(handler) -> object:
    import anthropic

    return anthropic.Anthropic(
        api_key="test-key", http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )


def _response(payload: dict, stop_reason: str = "end_turn") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "msg_test",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-5",
            "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
            "stop_reason": stop_reason,
            "stop_sequence": None,
            "usage": {"input_tokens": 1200, "output_tokens": 180},
        },
    )


def _sample_image(width: int = 2400, height: int = 1500) -> Image.Image:
    return Image.new("RGB", (width, height), "white")


def test_request_carries_image_and_ocr_text():
    """名刺画像とOCRテキストの両方を送る（画像だけ・テキストだけにしない）。"""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return _response(ANSWER)

    extractor = LlmFieldExtractor(client=_client(handler))
    extractor.extract(_sample_image(), OCR_TEXT)

    body = captured["body"]
    assert body["model"] == extractor.model
    assert body["output_config"]["effort"] == extractor.effort
    assert "名刺" in body["system"]

    blocks = body["messages"][0]["content"]
    kinds = [block["type"] for block in blocks]
    assert kinds == ["image", "text"]
    assert blocks[0]["source"]["media_type"] == "image/jpeg"
    assert blocks[0]["source"]["data"]  # base64 が入っている
    assert OCR_TEXT in blocks[1]["text"]


def test_schema_covers_all_fields():
    """構造化出力のスキーマに全項目が含まれ、余分なキーを許さない。"""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return _response(ANSWER)

    LlmFieldExtractor(client=_client(handler)).extract(_sample_image(), OCR_TEXT)

    schema = captured["body"]["output_config"]["format"]["schema"]
    assert set(ExtractedCardFields.model_fields) <= set(schema["properties"])
    assert schema["additionalProperties"] is False


def test_large_image_is_downscaled_before_sending():
    """OCRに必要な範囲を超える解像度で送らない（費用と転送量の抑制）。"""
    import base64
    import io

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return _response(ANSWER)

    LlmFieldExtractor(client=_client(handler)).extract(_sample_image(4000, 2500), OCR_TEXT)

    data = captured["body"]["messages"][0]["content"][0]["source"]["data"]
    sent = Image.open(io.BytesIO(base64.standard_b64decode(data)))
    assert max(sent.size) <= 1600


def test_result_shape_matches_rule_based_extractor():
    """戻り値の形をルールベースと揃える（呼び出し側を分岐させないため）。"""
    extractor = LlmFieldExtractor(client=_client(lambda request: _response(ANSWER)))
    parsed = extractor.extract(_sample_image(), OCR_TEXT)

    assert set(parsed["fields"]) == set(ExtractedCardFields.model_fields)
    assert parsed["fields"]["company_name"] == "株式会社サンプル商事"
    assert parsed["confidence"]["_overall"] > 0
    assert parsed["usage"]["input_tokens"] == 1200
    assert parsed["usage"]["output_tokens"] == 180


def test_refusal_is_reported_as_error():
    """拒否応答を正常な抽出結果として扱わない。"""
    extractor = LlmFieldExtractor(client=_client(lambda request: _response(ANSWER, stop_reason="refusal")))
    with pytest.raises(RuntimeError):
        extractor.extract(_sample_image(), OCR_TEXT)


def test_auto_falls_back_to_rule_when_llm_fails(monkeypatch):
    """auto ではLLMが失敗しても取込が止まらず、ルールベースで続行する。"""

    class Broken:
        def extract(self, image, text):
            raise RuntimeError("APIに到達できません")

    monkeypatch.setattr("bcards.services.ocr.get_llm_extractor", lambda: Broken())
    output = OcrOutput(provider="tesseract", api_version=None, text=OCR_TEXT, lines=OCR_TEXT.splitlines())

    parsed = extract_fields(_sample_image(), output, method="auto")
    assert parsed["method"] == "rule"
    assert parsed["fallback_reason"]
    assert parsed["fields"]["company_name"] == "株式会社サンプル商事"


def test_llm_method_without_credentials_is_an_error(monkeypatch):
    """llm を明示指定したのに使えない場合は、黙ってルールに落とさず知らせる。"""
    monkeypatch.setattr("bcards.services.ocr.get_llm_extractor", lambda: None)
    output = OcrOutput(provider="tesseract", api_version=None, text=OCR_TEXT, lines=OCR_TEXT.splitlines())

    with pytest.raises(RuntimeError):
        extract_fields(_sample_image(), output, method="llm")
