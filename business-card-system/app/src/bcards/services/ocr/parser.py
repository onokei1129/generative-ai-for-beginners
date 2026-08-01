"""OCRテキストから名刺の項目を分離する（要件§8「氏名、会社名、役職等の項目分離」）。

open-issues-v0.3.md 論点C の「方式1（汎用OCR＋ルールベース抽出）」に相当する実装。
LLMによる項目分離（方式2）へ差し替える場合も、戻り値の辞書構造は同じにする。
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

# 語を空白で区切らない文字（かな・漢字・全角記号）。この間の空白はOCRの癖。
# ハングルとキリル文字は語を空白で区切るため含めない。
CJK = (
    r"\u3000-\u303F"  # 全角の記号・句読点
    r"\u3040-\u30FF"  # ひらがな・カタカナ
    r"\u31F0-\u31FF"  # カタカナ拡張
    r"\u3400-\u4DBF"  # 漢字拡張A
    r"\u4E00-\u9FFF"  # 漢字
    r"\uF900-\uFAFF"  # 互換漢字
    r"\uFF00-\uFFEF"  # 全角英数・半角カナ
)

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
URL_RE = re.compile(r"(?:https?://|www\.)[\w\-./?%&=~+#:]+", re.IGNORECASE)
# 郵便番号。3桁-4桁だが、電話番号の一部（`070-9385`-4004）に当たってはいけない。
#
# 実データ（韓国の方の名刺）で `HP 070-9385-4004` の前半を郵便番号として取り、
# 残った `-4004` を住所にしていた。電話番号と見分けるため、前後を見る。
#
#   後ろ … 数字や区切りが続くならその番号の途中。郵便番号ではない。
#   前  … 数字が接しているならその番号の途中。ただし 〒 の読み違え
#          （`7100-0001`）だけは例外として通す。
POSTAL_MARKS = "〒〠亍干テT7"
POSTAL_RE = re.compile(
    rf"〒?\s*(?:(?<![\d\-ー－])|(?<=[{POSTAL_MARKS}]))(\d{{3}})\s*[-ー－]\s*(\d{{4}})(?![\d\-ー－])"
)
# 〒 は読み違えられやすい。郵便番号の直前に限って読み捨てる。
POSTAL_MARK_RE = re.compile(rf"[{POSTAL_MARKS}]\s*$")
# 電話番号。国番号つき（海外名刺）と国内表記の2通りを見る。
#
# 以前は国番号つきを `+81` だけ見ていたため、海外名刺の番号を1件も拾えなかった。
# 実測では英語の名刺で `TEL +1 212-555-0100` が空になっていた。区切りは国ごとに
# 様々（`+1 212-555-0100` / `+7 495 123-45-67` / `+44 (0)20 7123 4567`）なので、
# 国番号のあとは「数字と区切りの並び」として扱う。桁数は E.164 の15桁までに収める。
INTL_PHONE = r"\+\d{1,3}(?:[\s\-.()]{0,2}\d){6,14}"
DOMESTIC_PHONE = r"0\d{1,4}[-ー－(\s]\d{1,4}[)\-ー－\s]?\d{3,4}"
PHONE_RE = re.compile(f"(?:{INTL_PHONE}|{DOMESTIC_PHONE})")

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
    # 官公庁・士業など。実データの `沖縄県 東京事務所` が、法人格の語を含まず
    # メールのドメイン（pref.okinawa.lg.jp）とも一致しないため空になっていた。
    # `法律事務所` `設計事務所` にも効く。
    "事務所",
    "役所",
    "県庁",
    "市役所",
    "町役場",
    "村役場",
    "商工会議所",
    "組合",
    "Inc.",
    "Inc",
    "Corp.",
    "Corporation",
    "Co., Ltd",
    "Co.,Ltd",
    "Ltd.",
    "LLC",
    "K.K.",
    # 海外の法人格。実データに海外名刺が多く、これらを知らないと社名が空になる
    # （報告 5.1 の計測で、韓国語・中国語・ロシア語の名刺の社名が取れていなかった）。
    # 短すぎる略号（AG・SA・AB など）は別の語の一部に当たるため入れない。
    "주식회사",
    "유한회사",
    "(주)",
    "㈜",
    "有限公司",
    "股份公司",
    "集团",
    "集團",
    "有限責任公司",
    "ООО",
    "ЗАО",
    "ОАО",
    "ПАО",
    "GmbH",
    "S.A.",
    "S.A.S",
    "SARL",
    "B.V.",
    "N.V.",
    "Sdn Bhd",
    "Sdn. Bhd",
    "PLC",
    "LLP",
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


def has_company_keyword(line: str) -> bool:
    """法人格の語を含むかを、語の境界を見て判定する。

    英字の略号は別の語の一部に当たる。`S.A.` は住所の `U.S.A.` に当たり、
    住所の行が社名として登録されていた。

        `123 Main St, Chicago, U.S.A.` → 会社名 `123 Main St, Chicago, U.S.A.`

    英字の語は、直前が英字またはドットのときは数えない
    （`Acme S.A.` は数える。`U.S.A.` は数えない）。
    """
    for keyword in COMPANY_KEYWORDS:
        position = line.find(keyword)
        while position >= 0:
            before = line[position - 1] if position else ""
            if not (keyword[0].isascii() and (before.isalpha() or before == ".")):
                return True
            position = line.find(keyword, position + 1)
    return False

# 左右2段組みの名刺で、1行に混ざった段を分ける区切り。
#
# 名刺は左に社名・ロゴ、右に連絡先を置く体裁が多い。OCRは同じ高さにある文字を
# 1行にまとめて返すため、左段の飾り・ロゴと右段の本文が1行に混ざってしまう。
# 実データではこれが原因で、氏名・社名・部署・役職・ふりがなが総崩れになっていた。
#
#     `de Fh SHB eA        宮田 修`    ロゴの読み崩れ ＋ 氏名
#     `A                   とみた      おさむ`
#     `Sangeon Lee         T +82.2.6421.7777`
#     `Team Member         E eonlee@example.co.kr`
#     `mobile: 090-…       る 。`
#
# 段の間は必ず広く空くので、空白2つ以上を段の区切りとして分ける。
# 語の間の空白1つ（`沖縄県 東京事務所` `T E L:03-…` `佐々木 健`）は分けない。
COLUMN_GAP_RE = re.compile(r"[ \t　]{2,}")

TEL_LABELS = ("tel", "電話", "phone", "ｔｅｌ", "代表")
FAX_LABELS = ("fax", "ファックス", "ｆａｘ")
# 1文字のラベル。海外の名刺で連絡先の種別を頭文字だけで示す体裁が多い。
# 実データ（韓国の名刺）では `T +82.2.…` `F +82.2.…` `C +82.10.…` と並んでいて、
# ラベルが読めないため FAX と携帯が電話に押し出されて空になっていた。
#
# 誤って当たらないよう、前が英数字でなく、直後に番号が来る場合に限る。
SINGLE_LETTER_LABELS = {"t": "tel", "f": "fax", "c": "mobile", "m": "mobile"}
SINGLE_LETTER_LABEL_RE = re.compile(r"(?:^|(?<=[^A-Za-z0-9]))([TFCMtfcm])\s*(?=[+(]|\d)")
# `HP` は handphone。韓国・台湾・東南アジアの名刺で携帯の意味で使われる。
# 実データ（韓国の方の名刺）で `HP 070-9385-4004` を携帯と見分けられていなかった。
MOBILE_LABELS = ("mobile", "携帯", "cell", "ｍｏｂｉｌｅ", "hp", "h.p")

# 携帯の先頭3桁。050 はIP電話（固定）なので入れない。
# 実データで `Tel 050-3110-2873` を携帯として扱い、先に入っていた携帯に
# 押し出されて電話が空になっていた。
MOBILE_PREFIXES = ("090", "080", "070")

# 英字の行を氏名と間違えやすい語。実測では和英併記の名刺で `Head Office` を
# 氏名として登録し（姓 `Head` / 名 `Office`）、本来の氏名が空になっていた
# （合成サンプル16枚のうち4枚）。住所や建物の語であって人名ではない。
# 氏名と間違えやすい日本語の語。実データでは `へ特設サイトノ`（特設サイトの
# 案内）を氏名として登録し、姓『へ特』名『設サイトノ』になっていた。
NOT_A_NAME_WORDS_JA = (
    "特設",
    "サイト",
    "ホームページ",
    "ガイド",
    "案内",
    "公式",
    "会館",
    "ビル",
    "地図",
    "電話",
    "携帯",
    "メール",
    "検索",
)

NOT_A_NAME_WORDS = (
    "office",
    "building",
    "bldg",
    "floor",
    "tower",
    "street",
    "road",
    "avenue",
    "suite",
    "room",
    "branch",
    "factory",
    "laboratory",
    "center",
    "centre",
)

# 住所のラベル。`Add 〒580-0021 大阪府…` のように住所と同じ行に印字される。
# 英字の語は後ろに文字が続くものを除く（`Addison Road` を `ison Road` に
# しないため）。
ADDRESS_LABEL_RE = re.compile(
    r"^\s*(?:(?:address|adress|addr|add)(?![a-z])|住所|所在地)\s*[:：.．]?\s*",
    re.IGNORECASE,
)

# 「代表」に続くとき、電話のラベルではなく役職の一部だと分かる語。
NOT_A_TEL_LABEL_RE = re.compile(r"(?:取締役|取締|理事|社員|執行役|者)")

# 役職の語のあとに続いたとき、氏名ではなく役職の続きだと分かる語尾。
# `主任研究員` を役職『主任』＋氏名『研究員』に分けてしまうのを防ぐ。
TITLE_TAIL_WORDS = (
    "員",
    "長",
    "補佐",
    "代理",
    "心得",
    "待遇",
    "職",
    "官",
    "士",
    "係",
    "主任",
    "担当",
    "格",
)


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


def pick_title(line: str, keyword: str) -> str:
    """役職の行から登録する文字列を選ぶ。

    名刺は和英を1行に併記することが多い。実データでは

        `エグゼクティブ・プロデューサー / Executive Producer` → `プロデューサー`

    のように、複合語の後ろだけを取って前半を捨てていた。

    区切り（/｜｜など）があれば日本語側を採り、その中では語だけに
    切り詰めず、行そのもの（役職名の全体）を残す。
    """
    for separator in ("/", "|", "／", "｜", "・/"):
        if separator not in line:
            continue
        segments = [seg.strip() for seg in line.split(separator) if seg.strip()]
        japanese = [seg for seg in segments if _has_japanese(seg)]
        if japanese:
            # 日本語側に役職の語が含まれているものを選ぶ
            for seg in japanese:
                if keyword in seg:
                    return seg
            return japanese[0]
        # 日本語が無い行（英語だけの名刺）。役職の語を含む区切りを採る。
        # 実データでは `Chief Business Officer & Head of Japan | APAC` が
        # `Chief` になっていた。
        for seg in segments:
            if keyword in seg:
                return seg

    if line == keyword:
        return line
    # 「シニアエンジニア」「エグゼクティブ・プロデューサー」のように、
    # 役職の語に修飾が付いた形は全体が役職名。行が短ければそのまま残す。
    if len(line) <= len(keyword) + 12:
        return line
    return keyword


def split_department_and_title(line: str) -> tuple[str, str]:
    """1行に並んだ部署と役職を分ける。分けられなければ (行, "") を返す。

    名刺は「開発部 主任」「営業本部 第一営業部 部長」のように部署と役職を
    1行に印字することが多い。実測（合成サンプル16枚）では部署が

        `開発部 主任`            → 部署 `開発部主任`（正解は `開発部`）
        `営業本部 第一営業部 部長` → 部署 `営業本部第一営業部部長`

    のように役職を巻き込み、両方とも不一致になっていた。

    役職の語が行頭にある場合は分けない。「Sales Department」のように、
    役職の語で始まる部署名を役職と取り違えないため。
    """
    for keyword in sorted(TITLE_KEYWORDS, key=len, reverse=True):
        position = line.rfind(keyword)
        if position < 0:
            continue
        if position == 0:
            # 役職の語で始まる行。後ろに部署の語があれば部署名
            # （`Sales Department` の `Sales` を役職にしない）。
            # 無ければ役職の続き（`課長補佐` `部長代理`）なので部署にしない。
            # 実測では `課長補佐` が部署として登録され、役職が空になっていた。
            tail = line[len(keyword) :]
            if line == keyword or not any(word in tail for word in DEPARTMENT_KEYWORDS):
                return "", line
            return line, ""
        head, tail = line[:position].strip(), line[position:].strip()
        if head and any(word in head for word in DEPARTMENT_KEYWORDS):
            return head, tail
        # 部署の手がかりが無いなら、役職の一部（「シニアエンジニア」など）の可能性がある
        return line, ""
    return line, ""


def find_labels(line: str) -> list[tuple[int, str]]:
    """行の中の電話ラベルの位置と種別を、現れる順に返す。

    英字のラベルは語の先頭に限る。`hp`（handphone）のような短い語を
    単純な部分一致で探すと、別の語の一部（`graphpad` の `hp`）に当たる。
    後ろは縛らない。`telephone` の `tel`、`cellular` の `cell` を
    取り逃がさないため。
    """
    lowered = line.lower()
    found: list[tuple[int, str]] = []
    for match in SINGLE_LETTER_LABEL_RE.finditer(line):
        found.append((match.start(1), SINGLE_LETTER_LABELS[match.group(1).lower()]))
    for kind, labels in (("fax", FAX_LABELS), ("mobile", MOBILE_LABELS), ("tel", TEL_LABELS)):
        for label in labels:
            if label.isascii():
                pattern = rf"(?<![a-z0-9]){re.escape(label)}"
            else:
                pattern = re.escape(label)
            for match in re.finditer(pattern, lowered):
                # 「代表」は代表電話のラベルだが、「代表取締役」の一部でもある。
                # 役職の一部なら電話のラベルとして数えない。
                if label == "代表" and NOT_A_TEL_LABEL_RE.match(line, match.end()):
                    continue
                found.append((match.start(), kind))
    found.sort()
    return found


# OCRが拾う短いノイズ（`©` `_s` `Ob` `eC` `Ai` `AP` `LOBE`）。実データでは
# ロゴ・QRコード・飾り罫が英数字1〜4文字として読まれ、会社名や住所の前後に付いていた。
NOISE_TOKEN_RE = re.compile(
    r"^[A-Za-z0-9©®=_\-–—,.'\"|/\\+*~^`:;!?()\[\]{}<>。、・…‥「」『』【】〈〉〜※＊]{1,4}$"
)

# QRコードや飾りの四角は、四角い字として読まれる（実データでは住所の先頭に
# `回回` が入っていた）。同じ字が並ぶ短い塊はノイズとして扱う。
# 地名にも使う字なので、2文字以上の繰り返しに限る（`回` 1文字は落とさない）。
SQUARE_NOISE_RE = re.compile(r"^([回口ロ日目田■□▪▫●○◆◇])\1{1,3}$")


def trim_ocr_noise(text: str) -> str:
    """日本語の項目の前後に付いた短い英数字・記号を落とす。

    日本語を含まない行（`AONE GAMES` のような英字の社名）は触らない。
    4文字までに限るので、`Acme株式会社` の `Acme` は残る。
    """
    if not _has_japanese(text):
        return text
    def noise(token: str) -> bool:
        return bool(NOISE_TOKEN_RE.match(token) or SQUARE_NOISE_RE.match(token))

    tokens = [token for token in re.split(r"\s+", text.strip()) if token]
    while tokens and noise(tokens[0]):
        tokens.pop(0)
    while tokens and noise(tokens[-1]):
        tokens.pop()
    return " ".join(tokens)


def split_columns(line: str) -> list[str]:
    """左右2段組みの行を、段ごとに分ける（`COLUMN_GAP_RE` の説明を参照）。

    段が1つしか無い行はそのまま返す。
    """
    parts = [part.strip() for part in COLUMN_GAP_RE.split(line.strip())]
    parts = [part for part in parts if part]
    return parts if len(parts) > 1 else [line]


def japanese_segment(text: str) -> str:
    """行の中の日本語だけの部分を取り出す（いちばん長いもの）。

    実データでは氏名の行にロゴが混ざって読まれていた。

        `de Fh SHB eA        宮田 修` → `宮田 修`

    そのままでは氏名として判定できず、氏名が空になる。
    """
    segments = re.findall(r"[一-龥々〆ヶヵぁ-んァ-ヴー・][一-龥々〆ヶヵぁ-んァ-ヴー・\s]*", text)
    if not segments:
        return ""
    return max((segment.strip() for segment in segments), key=len)


def strip_phone_parts(text: str) -> str:
    """行から電話番号とそのラベルを取り除く。

    `代表取締役 090-1234-5678` のように役職と番号を1行に印字する名刺がある。
    番号を採った行を丸ごと使用済みにすると役職が空になるため、番号を外した
    残りを役職の候補として見る。

    「代表」は代表電話のラベルだが役職（代表取締役）の一部にもなるので消さない。
    """
    without_numbers = PHONE_RE.sub(" ", text)
    labels = [
        label
        for label in TEL_LABELS + FAX_LABELS + MOBILE_LABELS
        if label != "代表"
    ]
    for label in sorted(labels, key=len, reverse=True):
        without_numbers = re.sub(re.escape(label), " ", without_numbers, flags=re.IGNORECASE)
    return re.sub(r"[\s:：/|｜（）()]+", " ", without_numbers).strip()


def spaced_suffix(spaced: str, count: int) -> str:
    """空白を残した行から、末尾 count 文字（空白を数えない）を取り出す。

    氏名の分割には空白を残した行が要る（`ユン ソクン` → `ユン` / `ソクン`）。
    役職と同じ行から氏名を取り出すとき、空白を除いた側で位置を決めたあと、
    対応する部分を空白付きの行から取り直すために使う。
    """
    taken = 0
    for index in range(len(spaced) - 1, -1, -1):
        if spaced[index].isspace():
            continue
        taken += 1
        if taken == count:
            return spaced[index:].strip()
    return spaced.strip()


def strip_address_label(text: str) -> str:
    """住所の行頭に残ったラベル（`Add` `住所:`）を落とす。"""
    return ADDRESS_LABEL_RE.sub("", text).strip()


# 〒 のあとの数字が郵便番号として読めなかった残骸。実測では
# `〒530-0001 大阪府…` が `〒5390-0091 大阪府…` と読まれ、桁数が合わないため
# 郵便番号は取れず、住所が `〒5390-0091 大阪府…` になっていた。
# 郵便番号は空のままでよい（誤った番号を入れるより、空欄のほうが直しやすい）が、
# 住所に混ぜてはいけない。記号は 〒 に限る。`7-1-1 Chiyoda` の番地を削らないため。
POSTAL_JUNK_RE = re.compile(r"^[〒〠]\s*\d{1,8}(?:\s*[-ー－]\s*\d{1,8})?\s*")


def strip_postal_prefix(text: str) -> str:
    return POSTAL_JUNK_RE.sub("", text).strip()


# 住所らしさの最低限。読み崩れた断片を住所に入れないための歯止め。
#
# 実データ（8枚目）では住所が `〒4 らの - の９の` になっていた。`〒150-0022`
# の行が読み崩れたもので、数字も空白区切りの語も条件を満たすため、英字住所の
# 最終手段に拾われていた。住所には地名が要る——3文字以上のラテン語が2つ
# （`Nambusunhwan-ro` `Gangnam-gu`）か、漢字が2文字以上（`東京都渋谷区`）。
ADDRESS_WORD_RE = re.compile(r"[A-Za-z]{3,}")
KANJI_RE = re.compile(r"[\u4e00-\u9fff]")
KATAKANA_RE = re.compile(r"[\u30a1-\u30fa]")


# 住所に `@` は入らない。実データ（7枚目）では `Gangnam-gu` が
# `Gangnam@gu` と読まれていた。字の間のハイフンを `@` と読み違えたもので、
# 住所として登録する前に戻す。英数字に挟まれている `@` に限る
# （`@` で始まる SNS の ID などを壊さないため）。
ADDRESS_AT_RE = re.compile(r"(?<=[A-Za-z0-9])@(?=[A-Za-z0-9])")


def repair_address_symbols(text: str) -> str:
    return ADDRESS_AT_RE.sub("-", text)


def looks_like_address(text: str) -> bool:
    """住所には地名が要る。

    弾くのは、漢字もカタカナも英単語も無いもの——数字・記号・ひらがなだけの
    断片。日本の住所は必ず漢字（東京都）かカタカナ（ヒューマックス）を含み、
    海外の住所は英単語を含む。ひらがなだけの住所は無い。
    """
    if len(ADDRESS_WORD_RE.findall(text)) >= 2:
        return True
    if len(KANJI_RE.findall(text)) >= 2:
        return True
    return len(KATAKANA_RE.findall(text)) >= 3


def wrapped_blocks(lines: list[str], used: set[int]) -> list[tuple[int, int, str]]:
    """途中で折り返された住所を1つにまとめて返す。

    実データ（7枚目）の住所は3行に分かれて印字されていた。

        2621, Nambusunhwan-ro,
        Gangnam-gu, Seoul, Korea,
        06267

    1行ずつ見ると、1行目は語数が足りず、2行目は数字が無く、3行目は語数が
    足りないため、どれも住所として拾えず空になっていた。行末の読点は
    「次の行へ続く」という印なので、そこでつなぐ。
    """
    blocks: list[tuple[int, int, str]] = []
    for start in range(len(lines)):
        if start in used:
            continue
        end = start
        parts = [lines[start]]
        while parts[-1].rstrip().endswith((",", "、", "，")) and end + 1 < len(lines):
            if end + 1 in used:
                break
            end += 1
            parts.append(lines[end])
        blocks.append((start, end, " ".join(part.strip() for part in parts)))
    return blocks


def for_web_match(text: str) -> str:
    """メール・URLを探すための整形。

    OCRはドットの直後に空白を入れやすい。実測（合成サンプル16枚）では

        `https://www.example.co.jp` → `https://www. example. co. jp`

    となり、URLが `https://www.` で切れていた（16枚中4枚）。

    直した文字列はメール・URLの照合にだけ使い、他の項目には持ち込まない。
    住所や会社名にとっては、ここでの詰めすぎは害になるため。
    """
    # 「co. jp」は繋ぐが、「.jp Mobile」は繋がない（空白の直前がドットのときだけ詰める）
    return re.sub(r"(?<=\.)[ \t]+(?=[A-Za-z0-9])", "", text)


def recover_email_head(text: str, match: re.Match) -> str:
    """ローカル部のドットをカンマと読み違えたメールを繋ぎ直す。

    実測では `taro.yamada@example.co.jp` が `taro, yamada@example.co.jp` と
    読まれ、正規表現が `yamada@example.co.jp` しか拾えていなかった。

    直前の語が行頭か空白から始まるときだけ繋ぐ。`info@a.com, sales@b.com`
    のようにメールを2つ並べた行で、前のアドレスの末尾を巻き込まないため。
    """
    head = re.search(r"(?:^|(?<=\s))([A-Za-z0-9._%+\-]+)\s*,\s*$", text[: match.start()])
    if not head:
        return match.group(0)
    return f"{head.group(1)}.{match.group(0)}"


def strip_inner_spaces(text: str) -> str:
    """日本語文字の間に入った空白を除去する（tesseract の日本語出力対策）。

    注意: これは姓と名を区切る空白も消す。氏名・ふりがなの分割には
    この関数を通す前の文字列を使うこと（通すと「とみた おさむ」が
    「とみたおさむ」になり、文字数で機械的に分けてしまう）。

    対象は日本語・中国語の文字に限る。ハングルやキリル文字は語を空白で
    区切るため、消すと `주식회사 오모로봇` が `주식회사오모로봇` に、
    `ООО «Ромашка»` が `ООО«Ромашка»` になってしまう。
    """
    text = join_spaced_letters(text or "")
    return re.sub(rf"(?<=[{CJK}])\s+(?=[{CJK}])", "", text).strip()


def domestic_digits(value: str) -> str:
    """日本の番号を国内表記の数字列に揃える。それ以外は数字だけ残す。

    `+81 90-1234-5678` と `090-1234-5678` は同じ番号だが、`+81` のままでは
    別の値になる。これは2か所で問題になっていた。

    1. 種別の判定：携帯の先頭3桁（090/080/070/050）と照合できず、
       日本の携帯が固定電話として登録されていた
    2. 重複人物の判定：同じ人が2つの表記で別人として扱われていた

    他国の番号は携帯の見分け方が国ごとに違うため、国番号を残したまま返す
    （結果として「電話」に入る。誤って「携帯」に入れるより無害）。
    """
    text = normalize(value).strip()
    if text.startswith("+"):
        # 国際表記の「(0)」は「国内でかけるときだけ0を付ける」という慣習表記。
        # 付いている名刺と付いていない名刺で別の値にならないよう、先に落とす。
        text = re.sub(r"\(\s*0\s*\)", "", text)
    digits = re.sub(r"\D", "", text)
    if text.startswith("+") and digits.startswith("81"):
        return "0" + digits[2:]
    return digits


def normalize_phone(value: str) -> str:
    """照合・重複判定に使う正規形。

    保存時（card_contact.value_normalized）と検索時の両方で使うため、
    変えるときは既存データの詰め替えが必要になる
    （migrations/versions/…_normalize_phone_to_domestic_form）。
    """
    return domestic_digits(value)


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


def _is_hiragana_only(text: str) -> bool:
    """ふりがなの行かを判定する。

    ふりがなはひらがなで印字される。カタカナだけの行を「ふりがな」と見ると、
    外国名の名刺（`パトリシオ　バスケス`）で氏名が空になり、ふりがな欄に
    氏名が入る。実データで発生した。
    """
    stripped = re.sub(r"\s+", "", text)
    return bool(stripped) and bool(re.fullmatch(r"[ぁ-んー]+", stripped))


def _is_katakana_only(text: str) -> bool:
    stripped = re.sub(r"\s+", "", text)
    return bool(stripped) and bool(re.fullmatch(r"[ァ-ヶー・]+", stripped))


def _has_japanese(text: str) -> bool:
    return bool(re.search(r"[ぁ-んァ-ヶ一-龥]", text))


def _looks_like_person_name(line: str) -> bool:
    text = re.sub(r"\s+", "", normalize(line))
    if not (2 <= len(text) <= 12):
        return False
    if any(keyword in line for keyword in COMPANY_KEYWORDS + TITLE_KEYWORDS + DEPARTMENT_KEYWORDS):
        return False
    if any(word in text for word in NOT_A_NAME_WORDS_JA):
        return False
    if re.search(r"\d", text):
        return False
    # 住所の語を含む姓は珍しくない（`中村` `木村` `村上` `市川` `町田`）。
    # 1つ含むだけで弾くと、これらの氏名が空になる。住所は複数の語を含むので
    # 2つ以上のときだけ住所とみなす（番地のある行は上の数字の判定で弾いている）。
    if sum(hint in text for hint in ("都", "道", "府", "県", "市", "区", "町", "村")) >= 2:
        return False
    # 都道府県の語を含む長い行は組織名か住所（`沖縄県東京事務所`）。
    # 姓に含まれることはあっても、5文字を超えることはまず無い。
    if len(text) >= 5 and any(hint in text for hint in ("都", "道", "府", "県")):
        return False
    # 々（踊り字）を入れておくこと。`佐々木` `野々村` は珍しくない姓で、
    # 入れないと氏名として認識されない（実測で `主任 佐々木 健` の氏名が空になった）。
    if re.fullmatch(r"[一-龥々〆ヶヵぁ-んァ-ヴー・]{2,12}", text):
        return True
    latin = normalize(line).strip()
    if not re.fullmatch(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ.\-]*(?:\s+[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ.\-]*){1,2}", latin):
        return False
    lowered = latin.lower()
    if any(re.search(rf"\b{word}\b", lowered) for word in NOT_A_NAME_WORDS):
        return False
    # 全部大文字はロゴや社名の綴り（`AONE GAMES`）。人名は通常そう書かない。
    # 実データでロゴが氏名として登録されていた。
    return latin != latin.upper()


def split_person_name(full: str) -> tuple[str, str]:
    """姓と名に分割する。空白があればそこで、なければ日本語姓の一般的な長さで分ける。"""
    text = normalize(full)
    parts = [p for p in re.split(r"[\s　]+", text) if p]
    if len(parts) >= 3 and _is_kana_only(text):
        # かなの氏名・ふりがなは、OCRが語の途中にも空白を入れる。実測では
        #
        #   `やまだ たろう`      → `や まだ た ろう`   → `や` / `まだ た ろう`
        #   `すずき いちろう`    → `すず き いち ろう` → `すず` / `き いち ろう`
        #   `パトリシオ バスケス` → `パト リシオ バスケス` → `パト` / `リシオ バスケス`
        #
        # のように先頭の空白で切っていた（合成サンプル16枚のうち9枚でふりがなが不一致）。
        # どこが語の切れ目かは字面では決まらないので、長さの釣り合いが
        # いちばん良い位置で分ける（姓と名は極端に長さが違わない）。
        best = min(
            range(1, len(parts)),
            key=lambda at: abs(len("".join(parts[:at])) - len("".join(parts[at:]))),
        )
        return "".join(parts[:best]), "".join(parts[best:])
    # カタカナと漢字が混じる氏名は、字種の変わり目で分ける。
    # 実データでは `ジョンソン 裕子` が `ジョ ンソン 裕子` と読まれ、
    # 先頭の空白で切って `ジョ` / `ンソン 裕子` になっていた。
    compact = re.sub(r"[\s　]+", "", text)
    boundary = re.match(r"^([ァ-ヴー・]{2,})([一-龥々]{1,4})$", compact) or re.match(
        r"^([一-龥々]{1,4})([ァ-ヴー・]{2,})$", compact
    )
    if boundary:
        return boundary.group(1), boundary.group(2)

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
    for raw in lines:
        for line in split_columns(raw):
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
    # 電話番号だけのために消費した行。部署・役職はこの行からも探す。
    # `代表取締役 090-1234-5678` のように役職と番号を1行に印字する名刺があり、
    # 番号を採った時点で行ごと使用済みにすると役職が空になっていた。
    phone_used: set[int] = set()

    # メール・URL
    for index, line in enumerate(cleaned):
        candidate = for_web_match(line)
        if not fields["email"]:
            match = EMAIL_RE.search(candidate)
            if match:
                fields["email"] = recover_email_head(candidate, match)
                confidence["email"] = 0.95
                used.add(index)
        if not fields["url"]:
            match = URL_RE.search(candidate)
            if match and "@" not in match.group(0):
                fields["url"] = match.group(0).rstrip(".")
                confidence["url"] = 0.9
                used.add(index)

    # 電話・FAX・携帯
    # 「TEL 03-1234-5678  FAX 03-1234-5679」のように1行に複数載るため、
    # 各番号の直前にあるラベルを見て種別を判定する。
    for index, line in enumerate(cleaned):
        label_positions = find_labels(line)
        matches = list(PHONE_RE.finditer(line))

        for match in matches:
            number = match.group(0).strip(" \t-ー－.")
            digits = domestic_digits(number)
            if len(digits) < 9:
                continue
            labelled = [(position, kind) for position, kind in label_positions if position < match.start()]
            if not labelled:
                kind = "mobile" if digits[:3] in MOBILE_PREFIXES else "tel"
                score = 0.6
            else:
                position, kind = labelled[-1]
                score = 0.85
                # ラベルとこの番号の間に別の番号が挟まっているなら、そのラベルは
                # 前の番号のもの（`TEL 03-…／090-…` のような並び）。この場合だけ
                # 先頭3桁で見直す。ラベルが直に付いている番号は、ラベルを信じる
                # （`Tel 050-…` を携帯にしないため）。
                borrowed = any(
                    other.start() > position and other.end() <= match.start() for other in matches
                )
                if borrowed and kind == "tel" and digits[:3] in MOBILE_PREFIXES:
                    kind = "mobile"
                    score = 0.7
            if not fields[kind]:
                fields[kind] = number
                confidence[kind] = score
            used.add(index)
            phone_used.add(index)

    # 郵便番号・住所
    for index, line in enumerate(cleaned):
        match = POSTAL_RE.search(line)
        if match and not fields["postal_code"]:
            fields["postal_code"] = f"{match.group(1)}-{match.group(2)}"
            confidence["postal_code"] = 0.95
            # 〒 が読めずに残った1文字を住所の先頭に持ち込まない。
            # 実測では `〒100-0001 東京都…` が `7100-0001 東京都…` と読まれ、
            # 郵便番号を抜いたあとの住所が `7 東京都…` になっていた。
            # 郵便番号の直前に接している場合だけ落とすので、英字表記の
            # 「7-1-1 Chiyoda, 100-0001」のような住所は削らない。
            head = POSTAL_MARK_RE.sub("", line[: match.start()])
            remainder = strip_address_label((head + line[match.end() :]).strip())
            if remainder and not fields["address"]:
                fields["address"] = remainder
                confidence["address"] = 0.7
            used.add(index)

    if not fields["address"]:
        for index, line in enumerate(cleaned):
            if index in used:
                continue
            if len(line) >= 6 and sum(hint in line for hint in ADDRESS_HINTS) >= 2:
                fields["address"] = strip_postal_prefix(strip_address_label(line))
                confidence["address"] = 0.6
                used.add(index)
                break

    # 住所のラベルが付いた行。郵便番号が無く、日本の住所の手がかりも無い場合でも、
    # 名刺が「ここが住所」と書いているのだから、それに従う。
    if not fields["address"]:
        for index, line in enumerate(cleaned):
            if index in used or not ADDRESS_LABEL_RE.match(line):
                continue
            remainder = strip_address_label(line)
            if len(remainder) >= 4:
                fields["address"] = remainder
                confidence["address"] = 0.7
                used.add(index)
                break

    # 英字の住所。日本の住所の手がかり（都道府県市区町村）がまったく無いため、
    # 上の判定では拾えなかった。実データの
    #   `Santa Beatriz 111 of 1008, Providencia. Santiago de Chile`
    # が空になっていた。
    #
    # 住所が他から取れなかったときだけ動かす。番地があるので数字を含み、
    # 複数語からなる、いちばん長い行を選ぶ。氏名や社名は数字を含まないので
    # 巻き込まない。
    if not fields["address"]:
        candidates = []
        for start, end, line in wrapped_blocks(cleaned, used):
            if "@" in line or "http" in line.lower():
                continue
            # ドメインらしい語（`kaido-foods.example`）を含む行は住所ではない。
            # 実測で、読み崩れたURLの行が住所として入っていた。英字の住所にある
            # `Providencia. Santiago` は空白が入るのでここには当たらない。
            if re.search(r"[A-Za-z0-9]\.[A-Za-z]{2,}", line):
                continue
            if not re.search(r"\d", line):
                continue
            if len(line.split()) < 3:
                continue
            # 読み崩れた断片を住所にしない。`〒4 らの - の９の` を防ぐ。
            if not looks_like_address(line):
                continue
            candidates.append((len(line), start, end, line))
        if candidates:
            _, start, end, line = max(candidates)
            fields["address"] = strip_address_label(line)
            confidence["address"] = 0.4
            used.update(range(start, end + 1))

    # 会社名
    for index, line in enumerate(cleaned):
        if has_company_keyword(line):
            fields["company_name"] = line
            confidence["company_name"] = 0.9
            used.add(index)
            break

    # 法人格の語が無い社名（海外企業やロゴだけの表記）はメールのドメインで見つける。
    # 実データの `AONE GAMES` は `patricio@aonegames.com` と一致するが、
    # `株式会社` も `Inc.` も含まないため取れていなかった。
    if not fields["company_name"] and fields["email"]:
        domain = fields["email"].rsplit("@", 1)[-1]
        # co.jp / com などの一般部分を外して、会社を表す部分だけ残す。
        # 国別ドメインは国ごとに違う（`.kr` `.tw` `.cl`）ので、2文字の末尾を
        # まとめて外す。実データの `eonlee@nexongames.co.kr` は `.kr` を
        # 知らないため `NEXON GAMES` と照合できず、社名が空になっていた。
        host = re.sub(r"\.[a-z]{2}$", "", domain)
        host = re.sub(r"\.(?:co|or|ne|ac|go|com|net|org|jp|io|dev|app)$", "", host)
        host = re.sub(r"\.(?:co|or|ne|ac|go|com|net|org|jp)$", "", host)
        key = re.sub(r"[^a-z0-9]", "", host.lower())
        if len(key) >= 4:
            # ドメインは社名を縮めることがある（`edgecre` ← `Edge Creators`）ので、
            # 先頭が一致する行も同じ会社と見る。ただし読み崩れた断片にも当たる
            # （`時NEXO` がドメイン `nexongames` の先頭に一致した）ため、
            # 当たった行のうち**いちばん長いもの**を採る。
            matches: list[tuple[int, int, str]] = []
            for index, line in enumerate(cleaned):
                if index in used:
                    continue
                candidate = re.sub(r"[^a-z0-9]", "", line.lower())
                if len(candidate) >= 4 and (candidate.startswith(key) or key.startswith(candidate)):
                    matches.append((len(candidate), index, line))
            if matches:
                _, index, line = max(matches)
                fields["company_name"] = line
                confidence["company_name"] = 0.6
                used.add(index)

    # 部署
    for index, line in enumerate(cleaned):
        if index in used:
            continue
        if any(keyword in line for keyword in DEPARTMENT_KEYWORDS):
            department, title = split_department_and_title(line)
            if not department:
                continue  # 役職だけの行。部署として取らない
            fields["department_name"] = department
            confidence["department_name"] = 0.75
            if title:
                fields["title"] = title
                confidence["title"] = 0.8
            used.add(index)
            break

    # 役職（部署の行から取れなかった場合）
    #
    # 役職と氏名を1行に印字する名刺がある（`代表取締役 ユン ソクン`）。
    # 行を丸ごと役職にすると、役職が `代表取締役ユンソクン` になり、
    # そのうえ氏名が空になる（実データで発生）。役職のあとの残りが氏名らしければ、
    # 役職はその語だけにして、残りは氏名の候補として渡す。
    title_name: tuple[str, str] | None = None
    if not fields["title"]:
        for index, line in enumerate(cleaned):
            if index in used and index not in phone_used:
                # 部署として採った行から役職を拾い直さない。
                # 「Sales Department」の `Sales` を役職にしてしまう。
                continue
            candidate = strip_phone_parts(line) if index in phone_used else line
            if not candidate:
                continue
            for keyword in TITLE_KEYWORDS:
                if keyword not in candidate:
                    continue
                position = candidate.find(keyword)
                head = candidate[:position].strip()
                tail = candidate[position + len(keyword) :].strip()
                if (
                    not head
                    and len(tail) >= 3
                    and not any(tail.endswith(word) for word in TITLE_TAIL_WORDS)
                    and _looks_like_person_name(tail)
                ):
                    # 「課長補佐」「主任研究員」のような役職の続きと区別する。
                    # 氏名として通すのは3文字以上で、役職の語尾で終わらないものに限る
                    fields["title"] = keyword
                    # 空白を数えない字数で位置を決める（`John Smith` は10文字）
                    letters = len(re.sub(r"\s+", "", tail))
                    title_name = (tail, spaced_suffix(spaced_lines[index], letters))
                else:
                    fields["title"] = pick_title(candidate, keyword)
                confidence["title"] = 0.8
                used.add(index)
                break
            if fields["title"]:
                break

    # 氏名
    # ふりがな（ひらがな）の直後の行は氏名である可能性が高いので優先的に採用する。
    #
    # ただし直後もひらがなだけなら、それは氏名ではなくふりがなの続き。
    # 名刺は姓と名を大きく離して印字することがあり、そのぶん離れた
    # ふりがなが別々の行として読まれる（実データで発生）。
    #
    #     印字  とみた　　おさむ      読み  とみた
    #           冨田　　　修                おさむ
    #                                       冨田
    #                                       修
    #
    # 直さないと、`おさむ` を氏名と判断して 姓『お』名『さむ』になり、
    # 漢字の氏名は使われないまま捨てられる。
    name_index: int | None = None
    reading_index: int | None = None
    reading_tail: int | None = None
    for index, line in enumerate(cleaned):
        if index in used or not _is_hiragana_only(line):
            continue
        following = index + 1
        if following >= len(cleaned) or following in used:
            continue
        if _is_hiragana_only(cleaned[following]):
            continue  # ふりがなの続き。氏名ではない
        if not _looks_like_person_name(cleaned[following]):
            continue
        name_index = following
        reading_index = index
        previous = index - 1
        if previous >= 0 and previous not in used and _is_hiragana_only(cleaned[previous]):
            reading_index, reading_tail = previous, index
        break

    # 氏名の行にロゴが混ざって読まれることがある（`de Fh SHB eA  宮田 修`）。
    # 行そのままでは判定できないので、日本語の部分だけを取り出して見る。
    name_from_segment: str | None = None
    if name_index is None:
        # 日本語の氏名を英字の行より先に採る。日本語の名刺では氏名は日本語で
        # 印字されるので、英字だけの2語（`Edge Creators`）は屋号・ブランドの
        # ほうが多い。実データでは社名を氏名として登録し（姓 `Edge` / 名
        # `Creators`）、本来の氏名『坂本』が空になっていた。
        # 日本語の候補が無いときだけ英字を採るので、英語の名刺は変わらない。
        ascii_name: int | None = None
        for index, line in enumerate(cleaned):
            if index in used or _is_hiragana_only(line):
                continue
            if not _looks_like_person_name(line):
                continue
            if _has_japanese(line):
                name_index = index
                break
            if ascii_name is None:
                ascii_name = index
        if name_index is None:
            name_index = ascii_name

    # 行そのままでは氏名にならなかった場合にだけ、行の一部を見る。
    # 先に行そのままで探しきること。ロゴの読み崩れ（`トイ ヽ っ` の `トイ`）が
    # 本来の氏名の行より前にあると、そちらを氏名にしてしまう（実測で発生）。
    if name_index is None:
        for index, line in enumerate(cleaned):
            if index in used or _is_hiragana_only(line):
                continue
            segment = japanese_segment(spaced_lines[index])
            if not segment or _is_hiragana_only(segment):
                continue
            # 2文字の断片は氏名と見なさない。ロゴの読み崩れが当たりやすい
            if len(re.sub(r"\s+", "", segment)) < 3:
                continue
            if _looks_like_person_name(segment):
                name_index = index
                name_from_segment = segment
                break

    if name_index is None and title_name is not None:
        # 役職と同じ行に印字されていた氏名
        last, first = split_person_name(title_name[1])
        fields["last_name"], fields["first_name"] = last, first
        confidence["last_name"] = confidence["first_name"] = 0.6

    if name_index is not None:
        # 空白を残した行で分ける。「冨田　修」「佐々木 健」を取り違えないため
        last, first = split_person_name(name_from_segment or spaced_lines[name_index])
        fields["last_name"], fields["first_name"] = last, first
        confidence["last_name"] = confidence["first_name"] = 0.7
        used.add(name_index)

        # 姓と名が離れて印字され、別の行として読まれた場合（`冨田` / `修`）。
        # 次の行が短い漢字だけの行なら名として拾う。1文字の名（`修` `健`）が
        # あるため、氏名の判定（2文字以上）ではなく字種で見る。
        following = name_index + 1
        if (
            not first
            and following < len(cleaned)
            and following not in used
            # 3文字までに限る。4文字だと氏名がまるごと入った行（`伊藤直樹`）を
            # 名として取ってしまう（実測で発生）。
            and re.fullmatch(r"[一-龥々ァ-ヴー]{1,3}", cleaned[following])
            and not any(
                word in cleaned[following]
                for word in COMPANY_KEYWORDS + TITLE_KEYWORDS + DEPARTMENT_KEYWORDS
            )
        ):
            fields["first_name"] = cleaned[following]
            confidence["first_name"] = 0.6
            used.add(following)

    # ふりがな（ひらがなだけの行）
    #
    # カタカナだけの行はふりがなにしない。外国名の名刺はカタカナで氏名を
    # 印字するため（`パトリシオ　バスケス`）、ふりがな扱いにすると氏名が空になる。
    if reading_index is not None:
        head = split_person_name(spaced_lines[reading_index])
        if reading_tail is not None:
            # 姓と名のふりがなが別の行として読まれた場合
            fields["last_name_kana"] = re.sub(r"\s+", "", cleaned[reading_index])
            fields["first_name_kana"] = re.sub(r"\s+", "", cleaned[reading_tail])
            used.add(reading_tail)
        else:
            fields["last_name_kana"], fields["first_name_kana"] = head
        confidence["last_name_kana"] = 0.7
        used.add(reading_index)
    else:
        for index, line in enumerate(cleaned):
            if index in used:
                continue
            if not _is_hiragana_only(line) or not (2 <= len(re.sub(r"\s+", "", line)) <= 16):
                continue
            # ふりがなは漢字より必ず長くなる（`山田太郎` → `やまだたろう`）。
            # 氏名の行と同じか短いひらがなは、ふりがなではなく**かなの名**。
            #     `伊藤` + `しの`  → 姓『伊藤』 名『しの』
            # 直さないと、名が空になったうえに姓が『伊』『藤』に割れる。
            name_length = len(re.sub(r"\s+", "", cleaned[name_index])) if name_index is not None else 0
            reading_length = len(re.sub(r"\s+", "", line))
            # `伊 藤` のように姓だけが空白入りで読まれると、姓『伊』名『藤』に
            # 割れる。1文字ずつに割れているときは、姓と見て繋ぎ直す
            # （姓1文字＋名1文字の氏名もあるが、そのときは続く行がふりがなで、
            # 漢字より長くなるためここには来ない）。
            split_into_single_characters = (
                len(fields["last_name"]) == 1 and len(fields["first_name"]) == 1
            )
            if (
                name_index is not None
                and index > name_index
                and (not fields["first_name"] or split_into_single_characters)
                and reading_length <= name_length
            ):
                if split_into_single_characters:
                    fields["last_name"] += fields["first_name"]
                fields["first_name"] = re.sub(r"\s+", "", line)
                confidence["first_name"] = 0.6
                used.add(index)
                break
            # 姓と名のふりがなが、離れて印字されたぶん別々の行として読まれた場合
            # （`とみた` / `おさむ`）。氏名の行が直後に無くても対応する
            # ——実データでは、間にロゴの読み崩れと部署が挟まっていた。
            # 直さないと `とみた` を1行のふりがなと見て せい『とみ』めい『た』に割れる。
            following = index + 1
            if (
                following < len(cleaned)
                and following not in used
                and _is_hiragana_only(cleaned[following])
                and 2 <= len(cleaned[following]) <= 16
            ):
                fields["last_name_kana"] = re.sub(r"\s+", "", line)
                fields["first_name_kana"] = re.sub(r"\s+", "", cleaned[following])
                confidence["last_name_kana"] = 0.7
                used.add(index)
                used.add(following)
                break
            last, first = split_person_name(spaced_lines[index])
            fields["last_name_kana"], fields["first_name_kana"] = last, first
            confidence["last_name_kana"] = 0.7
            used.add(index)
            break

    # ロゴ・QRコード・飾り罫が英数字1〜4文字として読まれ、項目の前後に付く。
    # 実データでは会社名が `© 沖縄県東京事務所`、住所が
    # `Ob eC F 東京都千代田区平河町2-6-3 Ai AP APE LOBE` になっていた。
    for key in ("company_name", "department_name", "title", "address"):
        if fields[key]:
            fields[key] = trim_ocr_noise(fields[key])

    if fields["address"]:
        fields["address"] = repair_address_symbols(fields["address"])

    # 住所らしさの歯止めは、経路によらず最後に掛ける。
    #
    # はじめは英字住所の最終手段にだけ掛けていた。実テスト（8枚目）では
    # それとは別の経路から `〒4 らの - の９の` が入っており、直したはずの
    # 名刺で残ったままだった。どの経路で入ったものでも、住所として成り立た
    # ないものは載せない。空欄なら人が入れれば済むが、読み崩れた断片は
    # 誤りだと気づきにくい。
    if fields["address"] and not looks_like_address(fields["address"]):
        fields["address"] = ""
        confidence.pop("address", None)

    leftovers =[line for index, line in enumerate(cleaned) if index not in used]
    fields["note"] = "\n".join(leftovers)
    return {"fields": fields, "confidence": confidence}
