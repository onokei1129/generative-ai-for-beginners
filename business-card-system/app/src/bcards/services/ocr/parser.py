"""OCRテキストから名刺の項目を分離する（要件§8「氏名、会社名、役職等の項目分離」）。

open-issues-v0.3.md 論点C の「方式1（汎用OCR＋ルールベース抽出）」に相当する実装。
LLMによる項目分離（方式2）へ差し替える場合も、戻り値の辞書構造は同じにする。
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
URL_RE = re.compile(r"(?:https?://|www\.)[\w\-./?%&=~+#:]+", re.IGNORECASE)
POSTAL_RE = re.compile(r"〒?\s*(\d{3})\s*[-ー－]\s*(\d{4})")
PHONE_RE = re.compile(r"(?:\+81[\d\-() ]{8,}|0\d{1,4}[-ー－(\s]\d{1,4}[)\-ー－\s]?\d{3,4})")

COMPANY_KEYWORDS = (
    "株式会社",
    "有限会社",
    "合同会社",
    "合資会社",
    "合名会社",
    "一般社団法人",
    "公益社団法人",
    "一般財団法人",
    "医療法人",
    "学校法人",
    "特定非営利活動法人",
    "協同組合",
    "Inc.",
    "Inc",
    "Corp.",
    "Corporation",
    "Co., Ltd",
    "Co.,Ltd",
    "Ltd.",
    "LLC",
    "K.K.",
)

TITLE_KEYWORDS = (
    "代表取締役社長",
    "代表取締役",
    "代表社員",
    "代表理事",
    "取締役",
    "執行役員",
    "監査役",
    "会長",
    "社長",
    "副社長",
    "専務",
    "常務",
    "本部長",
    "支店長",
    "工場長",
    "部長",
    "次長",
    "課長",
    "係長",
    "室長",
    "所長",
    "主幹",
    "主査",
    "主任",
    "店長",
    "チーフ",
    "マネージャー",
    "マネジャー",
    "リーダー",
    "ディレクター",
    "プロデューサー",
    "コンサルタント",
    "エンジニア",
    "アナリスト",
    "スペシャリスト",
    "President",
    "CEO",
    "COO",
    "CTO",
    "CFO",
    "Director",
    "Manager",
    "Chief",
    "Head of",
    "Engineer",
    "Sales",
)

DEPARTMENT_KEYWORDS = (
    "事業部",
    "本部",
    "部門",
    "統括部",
    "推進部",
    "営業部",
    "開発部",
    "技術部",
    "管理部",
    "総務部",
    "人事部",
    "経理部",
    "財務部",
    "企画部",
    "広報部",
    "法務部",
    "情報システム",
    "研究所",
    "センター",
    "支社",
    "支店",
    "営業所",
    "工場",
    "課",
    "室",
    "グループ",
    "チーム",
    "Division",
    "Department",
    "Dept",
)

ADDRESS_HINTS = ("都", "道", "府", "県", "市", "区", "町", "村", "丁目", "番地", "-")

TEL_LABELS = ("tel", "電話", "phone", "ｔｅｌ", "代表")
FAX_LABELS = ("fax", "ファックス", "ｆａｘ")
MOBILE_LABELS = ("mobile", "携帯", "cell", "ｍｏｂｉｌｅ")

MOBILE_PREFIXES = ("090", "080", "070", "050")


def normalize(text: str) -> str:
    """全角英数字・記号を半角へ寄せる。"""
    return unicodedata.normalize("NFKC", text or "").strip()


def join_spaced_letters(text: str) -> str:
    """「Ｆ Ａ Ｘ」のように1文字ずつ離して印字された英字ラベルをつなぐ。

    名刺では TEL / FAX / E-mail を字間を空けて印字することが多い。
    そのままだと "fax" のラベル照合に失敗し、FAX番号が電話番号として
    登録されてしまう（実データで発生した）。
    """
    previous = None
    while previous != text:
        previous = text
        text = re.sub(r"\b([A-Za-z])[ \t]+(?=[A-Za-z]\b)", r"\1", text)
    return text


def strip_inner_spaces(text: str) -> str:
    """日本語文字の間に入った空白を除去する（tesseract の日本語出力対策）。

    注意: これは姓と名を区切る空白も消す。氏名・ふりがなの分割には
    この関数を通す前の文字列を使うこと（通すと「とみた おさむ」が
    「とみたおさむ」になり、文字数で機械的に分けてしまう）。
    """
    text = join_spaced_letters(text or "")
    return re.sub(r"(?<=[^\x00-\x7F])\s+(?=[^\x00-\x7F])", "", text).strip()


def normalize_phone(value: str) -> str:
    return re.sub(r"[^\d+]", "", normalize(value))


def normalize_name(value: str) -> str:
    return re.sub(r"\s+", "", normalize(value)).lower()


def normalize_company(value: str) -> str:
    text = normalize(value)
    for keyword in COMPANY_KEYWORDS:
        text = text.replace(keyword, "")
    return re.sub(r"[\s　\-・,.。、（）()]", "", text).lower()


def _is_kana_only(text: str) -> bool:
    stripped = re.sub(r"\s+", "", text)
    return bool(stripped) and bool(re.fullmatch(r"[ぁ-んァ-ヶー]+", stripped))


def _has_japanese(text: str) -> bool:
    return bool(re.search(r"[ぁ-んァ-ヶ一-龥]", text))


def _looks_like_person_name(line: str) -> bool:
    text = re.sub(r"\s+", "", normalize(line))
    if not (2 <= len(text) <= 12):
        return False
    if any(keyword in line for keyword in COMPANY_KEYWORDS + TITLE_KEYWORDS + DEPARTMENT_KEYWORDS):
        return False
    if re.search(r"\d", text):
        return False
    if any(hint in text for hint in ("都", "道", "府", "県", "市", "区", "町", "村")):
        return False
    return bool(re.fullmatch(r"[一-龥ぁ-んァ-ヶー]{2,12}", text)) or bool(
        re.fullmatch(r"[A-Za-z][A-Za-z.\-]*(?:\s+[A-Za-z][A-Za-z.\-]*){1,2}", normalize(line))
    )


def split_person_name(full: str) -> tuple[str, str]:
    """姓と名に分割する。空白があればそこで、なければ日本語姓の一般的な長さで分ける。"""
    text = normalize(full)
    parts = [p for p in re.split(r"[\s　]+", text) if p]
    if len(parts) >= 2:
        return parts[0], " ".join(parts[1:])
    if len(text) >= 4 and _has_japanese(text):
        return text[:2], text[2:]
    if len(text) == 3 and _has_japanese(text):
        return text[:2], text[2:]
    return text, ""


def parse_fields(lines: list[str]) -> dict[str, Any]:
    """OCRの行リストから名刺項目を抽出する。"""
    # spaced: 空白を残したまま正規化した行。氏名・ふりがなの分割に使う。
    # cleaned: さらに字間の空白を除いた行。ラベル照合や語の判定に使う。
    pairs = []
    for line in lines:
        spaced = join_spaced_letters(normalize(line)).strip()
        compact = strip_inner_spaces(normalize(line))
        if compact:
            pairs.append((compact, spaced))
    cleaned = [c for c, _ in pairs]
    spaced_lines = [s for _, s in pairs]

    fields: dict[str, Any] = {
        "last_name": "",
        "first_name": "",
        "last_name_kana": "",
        "first_name_kana": "",
        "company_name": "",
        "department_name": "",
        "title": "",
        "postal_code": "",
        "address": "",
        "tel": "",
        "mobile": "",
        "fax": "",
        "email": "",
        "url": "",
        "note": "",
    }
    confidence: dict[str, float] = {}
    used: set[int] = set()

    # メール・URL
    for index, line in enumerate(cleaned):
        if not fields["email"]:
            match = EMAIL_RE.search(line)
            if match:
                fields["email"] = match.group(0)
                confidence["email"] = 0.95
                used.add(index)
        if not fields["url"]:
            match = URL_RE.search(line)
            if match and "@" not in match.group(0):
                fields["url"] = match.group(0)
                confidence["url"] = 0.9
                used.add(index)

    # 電話・FAX・携帯
    # 「TEL 03-1234-5678  FAX 03-1234-5679」のように1行に複数載るため、
    # 各番号の直前にあるラベルを見て種別を判定する。
    for index, line in enumerate(cleaned):
        lowered = line.lower()
        label_positions: list[tuple[int, str]] = []
        for kind, labels in (("fax", FAX_LABELS), ("mobile", MOBILE_LABELS), ("tel", TEL_LABELS)):
            for label in labels:
                start = 0
                while True:
                    position = lowered.find(label, start)
                    if position < 0:
                        break
                    label_positions.append((position, kind))
                    start = position + 1
        label_positions.sort()

        for match in PHONE_RE.finditer(line):
            number = match.group(0).strip()
            digits = normalize_phone(number)
            if len(digits) < 9:
                continue
            preceding = [kind for position, kind in label_positions if position < match.start()]
            kind = preceding[-1] if preceding else None
            if kind is None:
                kind = "mobile" if digits[:3] in MOBILE_PREFIXES else "tel"
            elif kind == "tel" and digits[:3] in MOBILE_PREFIXES:
                kind = "mobile"
            if not fields[kind]:
                fields[kind] = number
                confidence[kind] = 0.85 if preceding else 0.6
            used.add(index)

    # 郵便番号・住所
    for index, line in enumerate(cleaned):
        match = POSTAL_RE.search(line)
        if match and not fields["postal_code"]:
            fields["postal_code"] = f"{match.group(1)}-{match.group(2)}"
            confidence["postal_code"] = 0.95
            remainder = POSTAL_RE.sub("", line).strip()
            if remainder and not fields["address"]:
                fields["address"] = remainder
                confidence["address"] = 0.7
            used.add(index)

    if not fields["address"]:
        for index, line in enumerate(cleaned):
            if index in used:
                continue
            if len(line) >= 6 and sum(hint in line for hint in ADDRESS_HINTS) >= 2:
                fields["address"] = line
                confidence["address"] = 0.6
                used.add(index)
                break

    # 会社名
    for index, line in enumerate(cleaned):
        if any(keyword in line for keyword in COMPANY_KEYWORDS):
            fields["company_name"] = line
            confidence["company_name"] = 0.9
            used.add(index)
            break

    # 部署
    for index, line in enumerate(cleaned):
        if index in used:
            continue
        if any(keyword in line for keyword in DEPARTMENT_KEYWORDS):
            fields["department_name"] = line
            confidence["department_name"] = 0.75
            used.add(index)
            break

    # 役職（部署と同じ行に含まれる場合は分離する）
    for index, line in enumerate(cleaned):
        for keyword in TITLE_KEYWORDS:
            if keyword in line:
                fields["title"] = keyword if line != keyword and len(line) > len(keyword) + 6 else line
                confidence["title"] = 0.8
                used.add(index)
                break
        if fields["title"]:
            break

    # 氏名
    # ふりがなの直後の行は氏名である可能性が高いので優先的に採用する。
    name_index: int | None = None
    for index, line in enumerate(cleaned):
        if index in used or not _is_kana_only(line):
            continue
        following = index + 1
        if following < len(cleaned) and following not in used and _looks_like_person_name(cleaned[following]):
            name_index = following
            break

    if name_index is None:
        for index, line in enumerate(cleaned):
            if index in used or _is_kana_only(line):
                continue
            if _looks_like_person_name(line):
                name_index = index
                break

    if name_index is not None:
        # 空白を残した行で分ける。「冨田　修」「佐々木 健」を取り違えないため
        last, first = split_person_name(spaced_lines[name_index])
        fields["last_name"], fields["first_name"] = last, first
        confidence["last_name"] = confidence["first_name"] = 0.7
        used.add(name_index)

    # ふりがな（かなだけの行）
    for index, line in enumerate(cleaned):
        if index in used:
            continue
        if _is_kana_only(line) and 2 <= len(re.sub(r"\s+", "", line)) <= 16:
            last, first = split_person_name(spaced_lines[index])
            fields["last_name_kana"], fields["first_name_kana"] = last, first
            confidence["last_name_kana"] = 0.7
            used.add(index)
            break

    leftovers = [line for index, line in enumerate(cleaned) if index not in used]
    fields["note"] = "\n".join(leftovers)
    return {"fields": fields, "confidence": confidence}
