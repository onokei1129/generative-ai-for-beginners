"""OCRサービスの選択（要件§8）。"""

from __future__ import annotations

import re

from PIL import Image

from ...config import settings
from .base import OcrOutput, OcrProvider
from .llm_extractor import get_llm_extractor
from .parser import email_backs_name as parser_email_backs_name
from .parser import parse_fields
from .providers import (
    AzureDocumentIntelligenceProvider,
    EasyOcrProvider,
    MockOcrProvider,
    PaddleOcrProvider,
    TesseractOcrProvider,
)

__all__ = [
    "OcrOutput",
    "OcrProvider",
    "get_provider",
    "recognize_card",
    "parse_fields",
    "extract_fields",
    "COMBINED",
    "COMBINED_ENGINES",
    "merge_fields",
]

_PROVIDERS = {
    "mock": MockOcrProvider,
    "tesseract": TesseractOcrProvider,
    "paddle": PaddleOcrProvider,
    "easyocr": EasyOcrProvider,
    "azure": AzureDocumentIntelligenceProvider,
}

# 2つの読み取りエンジンを両方かけて、項目ごとに取れたほうを採る構成。
#
# 論点Cの計測（ocr-decision-2026-08.md）で、両者の弱点が重ならないことが
# 分かった。EasyOCR は日本語の字を続けて読めるが英数字の記号を落とし
# （`foods.example` が `foodsexample`、`//` が `Il`）、tesseract は逆に
# 英数字は取れるが日本語を1字ずつ切って空白を挟む。
#
# 先に挙げたエンジンの値を優先し、空のときだけ次のエンジンの値を使う。
# 項目ごとに担当を決める案も測ったが、単純な優先順のほうが良かった。
COMBINED = "combined"
COMBINED_ENGINES = ("easyocr", "tesseract")


def get_provider(name: str | None = None) -> OcrProvider:
    key = (name or settings.ocr_provider or "mock").lower()
    factory = _PROVIDERS.get(key)
    if factory is None:
        raise ValueError(f"未知のOCRプロバイダです: {key}")
    try:
        return factory()
    except Exception:
        if key != "mock":
            # OCRサービスが利用できない場合でも取込フローは止めず、mock で代替する。
            # （実運用では管理者へ通知し、再処理で正しいプロバイダを使う）
            return MockOcrProvider()
        raise


def extract_fields(image: Image.Image, output: OcrOutput, method: str | None = None) -> dict:
    """OCR結果を項目に分離する（論点C：方式1=ルール / 方式2=LLM）。

    method: rule / llm / auto（既定。LLMが使えればLLM、無ければルール）
    """
    method = (method or settings.field_extractor or "rule").lower()
    if method in ("llm", "auto"):
        extractor = get_llm_extractor()
        if extractor is not None:
            try:
                parsed = extractor.extract(image, output.text)
                parsed["method"] = "llm"
                return parsed
            except Exception as exc:
                if method == "llm":
                    raise
                # auto の場合はルールベースへフォールバックする
                parsed = parse_fields(output.lines or output.text.splitlines())
                parsed["method"] = "rule"
                parsed["fallback_reason"] = str(exc)
                return parsed
        if method == "llm":
            raise RuntimeError(
                "LLMによる項目分離が要求されましたが、Claude API の認証情報が設定されていません。"
            )
    parsed = parse_fields(output.lines or output.text.splitlines())
    parsed["method"] = "rule"
    return parsed


# 形が決まっている項目だけ、採る前に形を確かめる。
#
# EasyOCR は英数字の記号を落とすため、空ではなく「もっともらしい誤り」を
# 返すことがある（`taro@example.co.jp` → `taro@exampleco.jp`）。空欄なら
# 人が気づくが、それらしい誤りは気づかずに登録されるため、形が違うものは
# 次のエンジンへ譲る。
#
# 合成サンプル20枚では、この検査の有無で正答率は変わらなかった（どちらも
# 76.8%）。防いでいるのは点数ではなく、見逃される誤りのほう。
_SHAPES = {
    "email": re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$"),
    "url": re.compile(r"^(?:https?://)?[^\s/]+\.[A-Za-z]{2,}"),
}


def _has_expected_shape(key: str, value: str) -> bool:
    shape = _SHAPES.get(key)
    return True if shape is None else bool(shape.match(value.strip()))


# 1行を分けて作る項目。別々のエンジンから寄せ集めると、1人の名前にならない。
#
# 実データ 13枚目では、EasyOCR が飾りを `町こ` と読んで姓に入れ、名は空、
# tesseract は `HIDEYA KOBAYASHI` を正しく読んでいた。項目ごとに採ると
# 姓『町こ』／ 名『HIDEYA』という別人ができあがる。
#
# まとめて片方から採る。どちらを採るかは埋まった数の多いほうで決める
# （姓も名も読めているエンジンのほうが確からしい）。同数なら先のエンジン。
_GROUPS = (
    ("last_name", "first_name"),
    ("last_name_kana", "first_name_kana"),
)


# 住所は「読めた分だけ入る」項目で、失敗のしかたは欠落。読み崩れは
# `looks_like_address` が先に落としているので、残ったものの中では長いほうが
# 情報が多い。実データ 17枚目では、EasyOCR の `Chiyoda-Ku TokyoJnPAN`（断片）
# が tesseract の全体を押しのけていた。
#
# 合成サンプル20枚では、長いほうを採っても正答率は変わらない（どちらも65%）。
_LONGEST_WINS = ("address",)

# 電話・携帯・FAX は「同じ番号」を別の欄に入れてはいけない。
# 実データ 21枚目の `Cell +82-10-8933-1438` は、EasyOCR が携帯、tesseract が
# 電話と判定し、項目ごとに採るため両方に同じ番号が入っていた。
_PHONE_KEYS = ("tel", "mobile", "fax")


def _prefer_longest(results: list[dict], fields: dict, confidence: dict) -> None:
    for key in _LONGEST_WINS:
        best = ""
        best_score = None
        for parsed in results:
            value = ((parsed.get("fields") or {}).get(key) or "").strip()
            if len(value) > len(best):
                best = value
                best_score = (parsed.get("confidence") or {}).get(key)
        if best:
            fields[key] = best
            if best_score is not None:
                confidence[key] = best_score


def _drop_repeated_numbers(fields: dict, confidence: dict) -> None:
    """同じ番号が複数の欄にあれば、根拠の強い欄だけに残す。

    根拠の強さは確信度で見る（ラベルを見て決めたものは 0.85、番号の頭だけ
    で決めたものは 0.6〜0.7）。同じなら電話・携帯・FAX の順で残す。
    """
    seen: dict[str, str] = {}
    for key in _PHONE_KEYS:
        value = (fields.get(key) or "").strip()
        if not value:
            continue
        digits = re.sub(r"\D", "", value)
        if not digits:
            continue
        kept = seen.get(digits)
        if kept is None:
            seen[digits] = key
            continue
        if (confidence.get(key) or 0) > (confidence.get(kept) or 0):
            fields[kept] = ""
            confidence.pop(kept, None)
            seen[digits] = key
        else:
            fields[key] = ""
            confidence.pop(key, None)


# 読み崩れとみなす長さ。これより長い日本語の氏名は、裏づけが無くても降ろさない。
#
# 日本語の名刺では、メールがローマ字の氏名を裏づけることが多い
# （`sachiko.hasegawa@gree.net`）。裏づけだけで選ぶと正しい漢字の氏名を
# 押しのけるので、短いものだけを対象にする。
#
#     巨メロ     3文字  → 降ろす（実テスト 7枚目）
#     竹廣乃葉   4文字  → 残す（実テスト 16枚目）
SHORT_ENOUGH_TO_DOUBT = 3


def _email_backs_group(parsed: dict, group: tuple, email: str) -> bool:
    """その氏名を、併合後のメールが裏づけるか。"""
    values = parsed.get("fields") or {}
    return any(
        parser_email_backs_name(values.get(key) or "", email) for key in group
    )


def _too_short_to_trust(parsed: dict, group: tuple) -> bool:
    values = parsed.get("fields") or {}
    joined = "".join((values.get(key) or "").strip() for key in group)
    return bool(joined) and len(joined) <= SHORT_ENOUGH_TO_DOUBT


def _merge_groups(results: list[dict], fields: dict, confidence: dict) -> None:
    email = (fields.get("email") or "").strip()
    for group in _GROUPS:
        best: dict | None = None
        best_filled = -1
        for parsed in results:
            values = parsed.get("fields") or {}
            filled = sum(1 for key in group if (values.get(key) or "").strip())
            # 埋まった数が同じでも、**メールが裏づけるほうが確からしい**。
            # ただし降ろすのは短い候補だけ（`SHORT_ENOUGH_TO_DOUBT` を参照）。
            if (
                filled == best_filled
                and best is not None
                and _too_short_to_trust(best, group)
                and not _email_backs_group(best, group, email)
                and _email_backs_group(parsed, group, email)
            ):
                best = parsed
                continue
            if filled > best_filled:
                best, best_filled = parsed, filled
        if best is None:
            continue
        values = best.get("fields") or {}
        scores = best.get("confidence") or {}
        for key in group:
            fields[key] = values.get(key, "")
            if scores.get(key) is not None:
                confidence[key] = scores[key]


def merge_fields(results: list[dict]) -> dict:
    """先に挙げた結果の値を優先し、空のときだけ次の結果の値を使う。

    形が決まっている項目で先の値が形を満たさない場合は、次の結果へ譲る。
    どこにも形を満たすものが無ければ、最初に見つけた値を残す（人が直せる
    ように、空にはしない）。確信度は採用した値のものを持ち回る。
    """
    fields: dict = {}
    confidence: dict = {}
    # 形を満たさないまま拾った値。形を満たすものが後から出れば置き換える。
    provisional: set[str] = set()

    for parsed in results:
        values = parsed.get("fields") or {}
        scores = parsed.get("confidence") or {}
        for key, value in values.items():
            if fields.get(key) and key not in provisional:
                continue
            if not value:
                fields.setdefault(key, value)
                continue
            good = _has_expected_shape(key, value)
            if fields.get(key) and not good:
                continue
            fields[key] = value
            if scores.get(key) is not None:
                confidence[key] = scores[key]
            elif key in confidence:
                del confidence[key]
            provisional.discard(key) if good else provisional.add(key)

    _merge_groups(results, fields, confidence)
    _prefer_longest(results, fields, confidence)
    _drop_repeated_numbers(fields, confidence)
    return {"fields": fields, "confidence": confidence, "method": "rule"}


def _recognize_combined(image: Image.Image) -> tuple[OcrOutput, dict]:
    """2つのエンジンを両方かけて併合する。

    片方が使えなければ、動いたほうだけで続ける。両方だめなら例外を出す
    （ここで mock に落とすと、擬似OCRの値を読み取り結果として保存してしまう）。
    """
    outputs: list[OcrOutput] = []
    parsed_list: list[dict] = []
    failures: list[str] = []
    for name in COMBINED_ENGINES:
        try:
            output = _PROVIDERS[name]().recognize(image)
        except Exception as exc:
            failures.append(f"{name}: {exc}")
            continue
        outputs.append(output)
        parsed_list.append(parse_fields(output.lines or output.text.splitlines()))

    if not outputs:
        raise RuntimeError("読み取りエンジンがどれも使えませんでした（" + " / ".join(failures) + "）")

    merged = OcrOutput(
        provider=COMBINED,
        api_version="+".join(filter(None, (o.api_version for o in outputs))) or None,
        # 確認画面の「OCRが読んだ文字を見る」に両方を出す。どちらが読めたのかを
        # 見分けられないと、報告を受けても原因を切り分けられない。
        text="\n".join(f"--- {o.provider} ---\n{o.text}" for o in outputs),
        lines=[line for o in outputs for line in (o.lines or [])],
        raw={"engines": [o.provider for o in outputs], "failures": failures},
        confidence=next((o.confidence for o in outputs if o.confidence is not None), None),
    )
    return merged, merge_fields(parsed_list)


# 読めたと言える項目。**形を確かめられるものだけ**を数える。
#
#   メール      `@` とドメインの形
#   電話・FAX   桁数と区切り
#   郵便番号    3桁-4桁
#   URL         スキームかドメインの形
#
# 氏名・住所・会社名は入れない。自由な文字列なので、読み崩れがいくらでも
# 似た形になる。実テスト 25枚目（縦書き）では、住所欄に
#
#     bEOO-SEI= YfEと szEZ:i〕E7fとEr_井子_料
#     soipms OOWVN IVQNV8        ← 記号を弾いたら別のゴミが通った
#
# が入り、そのたびに「読めた」と判定されて回して読み直す仕掛けが止まって
# いた。歯止めを足すたびに別のゴミが通る。証拠にしないのが筋。
#
# 住所と会社名しか無い名刺は、軽い下読みが2回増えるだけで結果は変わらない。
SOLID_FIELDS = ("email", "tel", "mobile", "fax", "postal_code", "url")

# 回したあとの下読みに使う読み取り機。モデルの読み込みが要らず速い。
# 向きが合っているかを見るだけなので、精度はここでは要らない。
PROBE_ENGINE = "tesseract"

# 下読みのときの画像の長辺。向きが合っているかを見るだけなので、
# 元の大きさは要らない。縮めるほど速い。
PROBE_MAX_SIDE = 1200


def shrink_for_probe(image: Image.Image) -> Image.Image:
    """下読み用に縮める。小さい画像はそのまま。"""
    longest = max(image.width, image.height)
    if longest <= PROBE_MAX_SIDE:
        return image
    scale = PROBE_MAX_SIDE / longest
    size = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
    return image.resize(size, Image.LANCZOS)


def looks_unreadable(parsed: dict) -> bool:
    """その読み取りが失敗しているか（`SOLID_FIELDS` がどれも取れていない）。"""
    values = parsed.get("fields") or {}
    return not any((values.get(key) or "").strip() for key in SOLID_FIELDS)


def _recognize_once(image: Image.Image, provider_name: str | None = None) -> tuple[OcrOutput, dict]:
    """画像を1回だけ読む。"""
    if (provider_name or settings.ocr_provider or "mock").lower() == COMBINED:
        return _recognize_combined(image)
    provider = get_provider(provider_name)
    output = provider.recognize(image)
    return output, extract_fields(image, output)


def recognize_card(image: Image.Image, provider_name: str | None = None) -> tuple[OcrOutput, dict]:
    """OCRを実行し、項目分離まで行う。結果の確定は利用者の確認後（要件§8）。

    **読めなかったときだけ、画像を回してもう一度読む。**

    縦書きの名刺（実テスト 22枚目）は、どちらの読み取り機も意味のある文字を
    1つも取れなかった。縦書きは紙ごと横倒しで取り込まれていることが多く、
    90度回せばふつうの横書きとして読める。

    回すかどうかは結果を見て決めるので、**読めた名刺は1回で終わり**。
    横書きの名刺は1枚も遅くならず、縦書きが何枚あるかを数えなくてよい。

    回したときは、まず**軽い読み取り機だけ**で下読みする。実測（大きめの
    読めない画像）で、重い読み取りを3回走らせると63秒かかった。1枚あたりの
    上限は120秒なので、実名刺（1回15〜18秒）では打ち切りに達する。
    下読みで手応えがあったときにだけ本読みする。
    """
    output, parsed = _recognize_once(image, provider_name)
    if not looks_unreadable(parsed):
        return output, parsed

    # 右回り・左回りの両方を試す。どちらに倒れているかは分からない。
    for angle in (270, 90):
        try:
            turned = image.rotate(angle, expand=True)
            _, probe = _recognize_once(shrink_for_probe(turned), PROBE_ENGINE)
        except Exception:  # noqa: BLE001 - 回して失敗しても元の結果で続ける
            continue
        if looks_unreadable(probe):
            continue
        # この向きなら読める。ここで初めて本読みする。
        try:
            return _recognize_once(turned, provider_name)
        except Exception:  # noqa: BLE001
            continue
    # 回しても読めなかった。元の結果を返す（空にして帰らない）。
    return output, parsed
