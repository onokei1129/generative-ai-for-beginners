"""OCRテキストから名刺の項目を分離する（要件§8「氏名、会社名、役職等の項目分離」）。

open-issues-v0.3.md 論点C の「方式1（汎用OCR＋ルールベース抽出）」に相当する実装。
LLMによる項目分離（方式2）へ差し替える場合も、戻り値の辞書構造は同じにする。
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from .romaji import name_to_hiragana

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
# URL。**ホスト名に点を必ず求める。**
#
# 以前は `https?://` のあとに文字が続きさえすれば通していたため、実テスト
# 34枚目（ITAKO）で `http://www itakoh.cojo/` が空白で切れた前半だけを拾い、
# URL欄に `http://www` が入っていた。ホストとして成立しておらず、意味が無い。
#
# 空欄なら人が気づいて入力できる。もっともらしい断片は、そのまま登録される。
URL_RE = re.compile(
    r"(?:https?://[\w\-]+(?:\.[\w\-]+)+|www\.[\w\-]+(?:\.[\w\-]+)*)"
    r"[\w\-./?%&=~+#:]*",
    re.IGNORECASE,
)
# 郵便番号。3桁-4桁だが、電話番号の一部（`070-9385`-4004）に当たってはいけない。
#
# 実データ（韓国の方の名刺）で `HP 070-9385-4004` の前半を郵便番号として取り、
# 残った `-4004` を住所にしていた。電話番号と見分けるため、前後を見る。
#
#   後ろ … 数字や区切りが続くならその番号の途中。郵便番号ではない。
#   前  … 数字が接しているならその番号の途中。ただし 〒 の読み違え
#          （`7100-0001`）だけは例外として通す。
#
# その例外は**その1文字自身の前**まで見ること。`7` や `T` は 〒 の読み崩れで
# あると同時にただの数字でもある。実テスト 23枚目の `Cell +82-10-7161-2135`
# では、`-7161-2135` の `7` を 〒 と見て郵便番号 `161-2135` を作っていた。
# 日本の名刺でも `TEL 03-7161-2135` で同じことが起きる。空欄なら人が気づくが、
# もっともらしい誤りは気づかれずに登録される。
POSTAL_MARKS = "〒〠亍干テT7"
POSTAL_RE = re.compile(
    rf"〒?\s*"
    rf"(?:(?<![\d\-ー－])|(?<=[{POSTAL_MARKS}])(?<![\d\-ー－][{POSTAL_MARKS}]))"
    rf"(\d{{3}})\s*[-ー－]\s*(\d{{4}})(?![\d\-ー－])"
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

# 市外局番を丸括弧で囲む書き方。実テスト34枚目（ITAKO）の `TEL (03) 6313-7096`
# が**空欄**になっていた。国内の形は先頭が `0` の並びだけを見ていたので、
# 頭に `(` が付くだけで外れる。印字にも読み取りにも問題は無く、こちらが
# 見ていなかった。
#
# 既存の形を緩めず、別の枝として足す。緩めると `TEL 03-7161-2135` の一部を
# 郵便番号にしていた類の、もっともらしい誤りに近づく。
PAREN_PHONE = r"\(0\d{1,4}\)\s*\d{1,4}[-ー－\s]?\d{3,4}"

# 丸括弧つきを先に見る。あとに置くと `DOMESTIC_PHONE` が括弧の中だけを
# 拾って `03) 6313-7096` のような欠けた形になる。
PHONE_RE = re.compile(f"(?:{INTL_PHONE}|{PAREN_PHONE}|{DOMESTIC_PHONE})")

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
    # 士業の法人。資格を役職として拾うようにしたため（実データ 22枚目）、
    # ここに無いと `サンプル弁護士法人` が会社名ではなく役職になる。
    "弁護士法人",
    "税理士法人",
    "司法書士法人",
    "行政書士法人",
    "社会保険労務士法人",
    "監査法人",
    "社会福祉法人",
    "宗教法人",
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
    # 実データ 16・18枚目。職種の語が無いため、行ごと氏名になっていた
    # （`水引アーティスト` → 姓『水引』／ 名『アーティスト』）。
    "アーティスト",
    "デザイナー",
    "プランナー",
    "ライター",
    "クリエイター",
    # 実データ 19枚目の `需給調整事業専門相談員`。
    "相談員",
    "指導員",
    # 士業の資格。氏名の上に印字され、役職の位置に来る（実データ 22枚目の
    # `公認会計士　税理士`）。`士` は「役職の語のあとに続く語尾」としては
    # 入っていたが、役職を**始める**語が無いため空欄になっていた。
    #
    # 長いほうを先に置くこと。`公認会計士` を `会計士` で切ると頭が落ちる。
    "公認会計士",
    "不動産鑑定士",
    "中小企業診断士",
    "社会保険労務士",
    "一級建築士",
    "二級建築士",
    "司法書士",
    "行政書士",
    "税理士",
    "会計士",
    "弁護士",
    "弁理士",
    "建築士",
    "技術士",
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
    # 実データ（7枚目）の `Team Member`。役職の語が無いため空になっていた。
    # `Board Member` `Staff Member` にも効く。
    "Member",
    # 実データ（`Principal Data Scientist`）。職種の語が無いため空になっていた。
    # いずれも職種を表す語で、社名・住所には出てこない。
    "Scientist",
    "Principal",
    "Officer",
    "Architect",
    "Analyst",
    "Specialist",
    "Researcher",
    "Consultant",
    # 実データ 14枚目の `Alex Kudishov ▪ Executive Producer`。役職の語が
    # 無いため行ごと氏名になり、姓が『Kudishov Executive Producer』だった。
    "Executive",
    "Producer",
    # 実データ 20枚目の `Representative in Japan`。
    "Representative",
    "Founder",
    "Partner",
    "Evangelist",
    "Designer",
    "Producer",
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
    # 官公庁の組織名（実データ 19枚目の `沖縄労働局 職業安定部`）。
    # 人の姓名にこれらの字は入らないので、氏名として拾わせない。
    #
    # なお `局` `庁` `署` は**組織の名前**の終わりでもある。ここに残すのは
    # 氏名として拾わせないためで、会社名と部署の切り分けは
    # `split_office_and_department` が行う。
    "局",
    "庁",
    "署",
    "安定部",
    "グループ",
    "チーム",
    "Division",
    "Department",
    "Dept",
)

ADDRESS_HINTS = ("都", "道", "府", "県", "市", "区", "町", "村", "丁目", "番地", "-")


# 官公庁の組織名の終わりを示す字。会社の名刺でいう `株式会社` にあたる。
# 都道府県庁・市役所などは COMPANY_KEYWORDS 側に既にある。
#
# `本部` は入れない。会社の部署名でもあるため、`営業本部 第一営業部 部長` が
# 組織名『営業本部』に切られてしまう。
OFFICE_SUFFIXES = ("労働局", "局", "庁", "署", "省")

# 組織名のうしろに部署が続くときの切れ目。
#     沖縄労働局 職業安定部
#         ↑ ここで切る
OFFICE_SPLIT_RE = re.compile(
    r"^(?P<office>.{2,}?(?:" + "|".join(OFFICE_SUFFIXES) + r"))[ 　]+(?P<rest>\S.*)$"
)


def is_office_name(line: str) -> bool:
    """行まるごとが官公庁の組織名か（`沖縄労働局`）。

    部署の語で終わる行（`情報システム室` `営業本部`）は部署なので外す。
    `本部` は組織名にも部署にも使われるため、ここでは組織名と見ない。
    """
    text = line.strip()
    if not text or has_company_keyword(text) or re.search(r"[ 　]", text):
        return False
    return len(text) >= 3 and text.endswith(("労働局", "局", "庁", "署", "省"))


def split_office_and_department(line: str) -> tuple[str, str] | None:
    """官公庁の行を、組織名と部署に分ける。分けられなければ None。

    会社の名刺なら `株式会社サンプル 営業本部` は会社名と部署に分かれる。
    官公庁でも同じように分かれるべきだが、`局` を部署の語に入れてあるため
    行まるごとが部署になり、**組織名の欄が空**になっていた（実テスト 18枚目
    `沖縄労働局 職業安定部`）。

    切るのは、空白のうしろが部署の語のときだけ。`沖縄労働局 那覇支所` の
    ように部署でないものが続く場合や、空白が無い場合は触らない。
    """
    match = OFFICE_SPLIT_RE.match(line.strip())
    if match is None:
        return None
    office, rest = match.group("office").strip(), match.group("rest").strip()
    if not office or not rest:
        return None
    # 組織名のうしろに来るのは部署。`部` `課` `室` で終わるものは、一覧に
    # 無い名前（`労働基準部`）でも部署として扱う。
    if not rest.endswith(("部", "課", "室", "係", "科", "所")) and not any(
        word in rest for word in DEPARTMENT_KEYWORDS
    ):
        return None
    # 会社の名刺はこれまでどおり。`株式会社` などが入る行はここで扱わない。
    if has_company_keyword(office):
        return None
    return office, rest


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
# `携` は読み崩れやすい（実テスト 20枚目で `捕帯`）。`帯` のほうは崩れにくく、
# 名刺で電話番号の近くに出る `帯` は携帯以外にほぼ無いので、これも見る。
MOBILE_LABELS = ("mobile", "携帯", "帯", "cell", "ｍｏｂｉｌｅ", "hp", "h.p")

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
    # 役職の部品。役職は1文字でも読み崩れると役職の語に一致しなくなり、
    # 漢字2文字＋漢字3文字の並びが氏名の形に見えてそのまま姓と名になる。
    #
    #     30枚目  印字 代表取締役  →  姓『代表』名『取締彼』
    #     28枚目  印字 執行役員    →  姓『勢行』名『役員』
    #
    # 読み崩れる語をすべて数え上げることはできないので、**崩れにくい部品**の
    # ほうを見る。これらは氏名にはまず現れない。
    #
    # `執行` は姓として実在するため入れない（同じ行の `役員` で止まる）。
    "代表",
    "取締",
    "役員",
    "常務",
    "専務",
    "監査",
    "顧問",
    "相談役",
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
    # 職務を表す語。役職・部署の行であって氏名ではない。実データ 10枚目
    # （ロシアの名刺）では `Game Business Development` を 姓『Business
    # Development』名『Game』として登録していた。
    "business",
    "development",
    "marketing",
    "sales",
    "engineering",
    "operations",
    "planning",
    "management",
    "division",
    "department",
    "dept",
    "team",
    # 国・地域の語。役職・部署では担当範囲としてよく出るが（`Head of Japan |
    # APAC`・`日本支社`）、人名にはまず現れない。
    #
    # 実データ 20枚目では、印字は `Representative in Japan` なのに easyocr が
    # `Represenialivein Japan` と読み崩し、姓『Japan』名『Represenialivein』
    # として登録していた。`representative` は下の語彙に入っているが、読み崩れた
    # 側は一致しない。**読み崩れる語をすべて数え上げることはできない**ので、
    # 崩れにくい短い語のほうを見る。
    "japan",
    "korea",
    "china",
    "taiwan",
    "asia",
    "pacific",
    "apac",
    "emea",
    "europe",
    "america",
    "americas",
    "global",
    "international",
    "worldwide",
    "region",
    "regional",
    # `Republic of Korea` の `Korea` は上にあるが、OCRが空白を落として
    # `ofKorea` になると語として一致しない（実テスト 20枚目）。手前で止める。
    "republic",
    # 会社の形態を表す語。`has_company_keyword` は `Inc.` や `GmbH` を見るが
    # `Acme Ltd` `ACME CORP` は素通りし、姓『Ltd』名『Acme』になっていた。
    "corp",
    "corporation",
    "ltd",
    "limited",
    "llc",
    "llp",
    "inc",
    "incorporated",
    "company",
    "holdings",
    "gmbh",
    "plc",
    "pte",
    # 日本の会社の種類をラテン文字で示すもの。`G.K.` は合同会社、
    # `K.K.` は株式会社。実テスト 8枚目では、社名 `Causal Foundry G.K.` が
    # 2行に分かれて読まれ、姓『Foundry GK』名『Causal』になっていた。
    # 点は `normalize` で残るので、点無しの形も併せて挙げる。
    "gk",
    "g.k.",
    "kk",
    "k.k.",
)


def email_backs_name(line: str, email: str) -> bool:
    """その行の語が、メールアドレスの `@` より前に現れるか。

    名刺のアドレスは氏名から作られることが多い（`eonlee@…` `ana@…`
    `sachiko.hasegawa@…`）。読み崩れた断片と本物の氏名を形だけで
    見分けられないとき、これが裏づけになる。

    2文字以下の語は見ない（偶然当たる）。
    """
    if not email or "@" not in email:
        return False
    local = email.split("@", 1)[0].lower()
    words = [word for word in re.split(r"[^0-9A-Za-zぁ-んァ-ヴ一-鿿]+", line) if len(word) >= 3]
    return any(word.lower() in local for word in words)


def has_not_a_name_word(lowered: str) -> bool:
    """氏名にならない語が含まれるか（`NOT_A_NAME_WORDS`）。

    語の切れ目で見る。`hp` を単純な部分一致で探すと `graphpad` に当たる。
    ただし `g.k.` のように記号で終わる語は、後ろに切れ目が立たない
    （`\\b` は英数字と非英数字の境目にしか置かれない）。そういう語は
    前だけを縛る。
    """
    for word in NOT_A_NAME_WORDS:
        head = r"\b" if word[0].isalnum() else ""
        tail = r"\b" if word[-1].isalnum() else ""
        if re.search(rf"{head}{re.escape(word)}{tail}", lowered):
            return True
    return False

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

# 漢字（と踊り字）だけでできた行と、そのときの氏名の長さの上限。
# 由来は `_looks_like_person_name` の説明を参照。
KANJI_ONLY_RE = re.compile(r"[一-龥々〆]+")
MAX_KANJI_NAME = 8


# 横棒に見えて、日本語の語の中には出てこない文字。ASCII のハイフンへ寄せる。
#
# NFKC は全角の `－` を直すが、これらは直さない。郵便番号・電話番号の判定は
# ASCII の `-` を見ているため、寄せておかないと**読めているのに空欄**になる
# （実テスト 9枚目。画面には `テ150‐0022` と出るのに郵便番号が入らない）。
#
# **`ー`（U+30FC 長音記号）は入れないこと。**「ヒューマックス」のように日本語の
# 語の一部として現れる。郵便番号・電話番号の側で個別に見ている今のやり方を変えない。
DASH_TO_HYPHEN = str.maketrans(dict.fromkeys("‐‑‒–—―−", "-"))

# 住所の先頭に置かれた海外の郵便番号（`125167, Moscow,` 実テスト 10枚目）。
#
# 番地が先頭に来る住所（`2621, Nambusunhwan-ro,` 実テスト 8枚目）と形が同じ
# なので、**5〜6桁で、直後に読点がある**ときだけ外す。韓国の番地 `2621` は
# 4桁なので当たらず、`12345 Main Street` は読点が無いので当たらない。
LEADING_POSTAL_RE = re.compile(r"^(\d{5,6})\s*,\s*")

# 住所の末尾に置かれた海外の郵便番号（`…, Republic of Korea, 13591`
# 実テスト 23枚目）。読点で区切られた最後の数字だけを見るので、番地
# （`3-11`）や建物の階（`8F`）には当たらない。
TRAILING_POSTAL_RE = re.compile(r"\s*,\s*(\d{5,6})\s*$")


def normalize(text: str) -> str:
    """全角英数字・記号を半角へ寄せ、横棒をハイフンへそろえる。"""
    return unicodedata.normalize("NFKC", text or "").translate(DASH_TO_HYPHEN).strip()


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
    # 役職の語の前が、語と違う字種なら読み崩れ。そこから後ろだけを採る。
    #
    # 複合した役職は1つの字種で書く（`Executive Producer` `シニアエンジニア`）。
    # 実データ 20枚目では、tesseract が `ん い Representative in Japan` と
    # 読み、`んい` ごと役職にしていた。
    position = line.find(keyword)
    head = line[:position].strip()
    if head and _has_japanese(head) != _has_japanese(keyword):
        line = line[position:].strip()
    # 「シニアエンジニア」「エグゼクティブ・プロデューサー」のように、
    # 役職の語に修飾が付いた形は全体が役職名。行が短ければそのまま残す。
    #
    # 許す長さは字種で変える。英語は語を空白で区切るぶん長くなる（実データの
    # `Principal Data Scientist` は24文字あり、`Scientist` だけになっていた）。
    margin = 12 if _has_japanese(line) else 24
    if len(line) <= len(keyword) + margin:
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


# 続きの部署の行にだけ使う語。単独では部署と決められない。
#
# `Team` `Group` は部署にも役職にも出る（`Team Manager`）。最初の1行を
# これで拾うと役職を部署にしてしまうので、**すでに部署と分かった行の
# 隣にある**ときだけ続きとみなす。
# `Office` `Unit` `Section` は入れない。`Office` は住所にも出るため
# （`NOT_A_NAME_WORDS` に住所の語として入っている）、住所の行を部署に
# つないでしまう。実測で部署の正答率が 65% → 50% に落ちた。
DEPARTMENT_RUN_WORDS = DEPARTMENT_KEYWORDS + ("Team", "Group")


def _is_department_run_line(line: str) -> bool:
    """部署の続きになりうる行か。役職の語を含む行は続きにしない。"""
    if not line.strip():
        return False
    if any(word in line for word in TITLE_KEYWORDS):
        return False
    return any(word in line for word in DEPARTMENT_RUN_WORDS)


def _department_run(
    lines: list[str], index: int, used: set[int]
) -> tuple[list[str], list[str]]:
    """部署の行の並びを、前後にたどって集める。

    組織の階層を上から順に刷る名刺がある。1行しか取らないと**どの部署に
    属するのか分からなくなる**（実テスト 22枚目は3行のうち最後の1行だけ）。

        Store Business Management Team
        Publishing&Platform ESD Business Division
        Megaport Division Group

    見つけた行が並びの途中のこともあるので、前にもさかのぼる。
    """
    before: list[str] = []
    for at in range(index - 1, -1, -1):
        if at in used or not _is_department_run_line(lines[at]):
            break
        before.insert(0, lines[at])
        used.add(at)

    after: list[str] = []
    for at in range(index + 1, len(lines)):
        if at in used or not _is_department_run_line(lines[at]):
            break
        after.append(lines[at])
        used.add(at)
    return before, after


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


# 行頭に付いたロゴ・アイコンの読み崩れ（実データ 10・11枚目の `@` と `x)`）。
#
# `trim_ocr_noise` は日本語を含む行しか見ないため、英字だけの行に効かない。
# 11枚目では、これで社名が空になっていた。社名はメールのドメインとの前方
# 一致で見つけるが、照合に使う文字列が行頭の `x` を含んで `xedgecreators`
# になり、`edgecre` と一致しなかった。
#
# 落とすのは**記号を含む短い塊**だけ。`Edge Creators` の `Edge` のように
# 記号を含まない語まで落とすと、社名そのものが消える。
def _continues_into_next_line(text: str) -> bool:
    """英字の住所の折り返しか（読点で終わる行）。

    日本語の住所は読点で終わらないので、日本語を含む行は対象にしない。
    住所以外の行を巻き込まないよう、番地らしい数字を含むことも求める。
    """
    stripped = text.strip()
    if not stripped.endswith(",") or _has_japanese(stripped):
        return False
    return bool(re.search(r"\d", stripped)) and len(stripped.split()) >= 2


def _nearest_hiragana_line(lines: list[str], index: int, step: int) -> str | None:
    """その向きで最初に見つかるひらがなの行。無ければ None。"""
    at = index + step
    while 0 <= at < len(lines):
        line = lines[at]
        if line and (_is_hiragana_only(line) or _is_hiragana_sentence(line)):
            return line
        at += step
    return None


def _belongs_to_a_slogan(lines: list[str], index: int) -> bool:
    """その行が、読点で終わったひらがなの文の一部か。

    **前後の両方を見る。** 読み取り機が返す行の順番は印字の順番と違い、
    標語の2行が入れ替わることがある。実テスト19枚目（沖縄労働局）の
    ロゴの標語では、tesseract が逆順に読んでいた:

        印字        ひと、くらし、
                    みらいのために

        tesseract   みらい の た め に      ← こちらが先
                    ひと 、 く らし 、       ← 読点で終わる行が後ろ

    手前しか見ていなかったため、この向きでは歯止めが効かず、
    せい『みらいの』／めい『ために』としてふりがなに入っていた。

    どちらの向きでも、**最初に見つかるひらがなの行**だけを見る。間に別の
    ひらがなの行があれば、そちらが続きなので打ち切る。
    """
    def unfinished(line: str | None) -> bool:
        return bool(
            line
            and _is_hiragana_sentence(line)
            and re.search(r"[、,；;・]$", line)
        )

    return unfinished(_nearest_hiragana_line(lines, index, -1)) or unfinished(
        _nearest_hiragana_line(lines, index, 1)
    )


def _is_hiragana_sentence(text: str) -> bool:
    """ひらがなに読点・区切りが付いた行か（文の一部）。

    ふりがなには読点が入らない。標語やキャッチコピーは入る
    （実データ 19枚目の `ひと、くらし、`）。
    """
    if not re.search(r"[、,；;。・]", text):
        return False
    body = re.sub(r"[、,；;。・\s]", "", text)
    return bool(body) and bool(re.fullmatch(r"[ぁ-んー]+", body))


def drop_unmatched_prefix(line: str, key: str) -> str:
    """社名の行から、ドメインとの一致に効いていない先頭の塊を落とす。

    社名はメールのドメインとの前方一致で見つける。照合は英数字だけを見て
    行うため、行の先頭にアイコンの読み崩れが付いていても一致してしまい、
    それがそのまま社名になる（実データ 18枚目の `個 kimusubitokyo`）。

    先頭の塊を1つずつ外し、外しても一致が保たれるあいだは外す。
    """

    def matches(text: str) -> bool:
        compact = re.sub(r"[^a-z0-9]", "", text.lower())
        return len(compact) >= 4 and (compact.startswith(key) or key.startswith(compact))

    tokens = [token for token in re.split(r"\s+", line.strip()) if token]
    while len(tokens) > 1 and matches(" ".join(tokens[1:])):
        tokens.pop(0)
    return " ".join(tokens)


def strip_leading_noise(text: str) -> str:
    """行頭のノイズを1つ落とす。字種は問わない。

    ノイズとみなすのは、空白までの最初の塊が
      * 英数字を1つも含まない（`@` `=:`）、または
      * 2文字までで、記号を含み、数字を含まない（`x)`）
    場合だけ。`e-mail:` のようなラベルは3文字を超えるので残る。

    数字を含むものは落とさないこと。国際電話の `+7 916 737-23-13` は
    `+7` が2文字で記号を含むため、この例外が無いと `916 737-23-13` に
    なる（実データ 10枚目で実際に壊した）。
    """
    stripped = text.strip()
    if not stripped:
        return ""
    head, _, tail = stripped.partition(" ")
    has_letter = bool(re.search(r"[^\W_]", head, re.UNICODE))
    has_symbol = bool(re.search(r"[^\w\s]", head, re.UNICODE))
    has_digit = bool(re.search(r"\d", head))
    if has_letter and not (len(head) <= 2 and has_symbol and not has_digit):
        return stripped
    return tail.strip()


# 階数だけの語。`8F` `12F` `B1F` `3階`。住所の末尾で落とさないために使う。
FLOOR_TOKEN_RE = re.compile(r"[Bb]?\d{1,3}\s*(?:[FfＦ]|階)")


def trim_ocr_noise(text: str, keep_house_number: bool = False) -> str:
    """日本語の項目の前後に付いた短い英数字・記号を落とす。

    日本語を含まない行（`AONE GAMES` のような英字の社名）は触らない。
    4文字までに限るので、`Acme株式会社` の `Acme` は残る。

    住所の末尾の番地は落とさないこと（`keep_house_number`）。番地は短い
    英数字なのでノイズと同じ形をしている。実データ（3枚目）では

        大阪府松原市高見の里六丁目 7-18  →  大阪府松原市高見の里六丁目

    と番地が消えていた。`7-18` は4文字でノイズの上限にちょうど当たる。
    `1-1-1` は5文字で残るため、番地の桁数しだいで消えたり残ったりしていた。

    階数も同じ形をしている。`○○タワー 12F` の `12F` は3文字でノイズと
    見分けが付かず、住所から階が消えていた（`5階` は「階」が日本語なので
    残り、`8F` は消える、という一貫しない結果になっていた）。
    """
    if not _has_japanese(text):
        return text
    def noise(token: str) -> bool:
        return bool(NOISE_TOKEN_RE.match(token) or SQUARE_NOISE_RE.match(token))

    tokens = [token for token in re.split(r"\s+", text.strip()) if token]
    while tokens and noise(tokens[0]):
        tokens.pop(0)
    while tokens and noise(tokens[-1]):
        if keep_house_number and (
            is_house_number_only(tokens[-1]) or FLOOR_TOKEN_RE.fullmatch(tokens[-1])
        ):
            break
        tokens.pop()
    return " ".join(tokens)


# 住所の末尾で番地の前に空いた空白。日本語の住所は番地の前で空けないので、
# OCRが字間に入れたもの。実データでは `六丁目 7-18` と空いて読まれていた。
HOUSE_NUMBER_TAIL_RE = re.compile(
    r"(?<=[぀-ヿ一-鿿])\s+(\d{1,4}(?:-\d{1,4}){0,3})$"
)


def join_house_number(text: str) -> str:
    """住所の末尾にある番地の前の空白を詰める。"""
    return HOUSE_NUMBER_TAIL_RE.sub(r"\1", text)


def _name_halves_are_whole(parts: list[str]) -> bool:
    """段に切ったときの**最後の断片**が、名として成り立つ長さか。

    `藤   し` は「伊藤 しの」の読み崩れで、`し` は名ではない。一方
    `迎　　　亮一` の `亮一` は名。姓が1文字（`迎`）のことはあるが、
    右端が1文字の断片なら氏名の途中ではなく段の切れ目とみなす。

    ただし**漢字1文字の名**は実在する（徹・修・誠）。かなと漢字で分ける。
    `し` は名ではないが、`徹` は名（実テスト 21枚目 `高 岡   徹`）。
    """
    if len(parts) < 2:
        return True
    tail = re.sub(r"\s+", "", parts[-1])
    if len(tail) < 2 and not re.fullmatch(r"[一-鿿]", tail):
        return False
    # 片側だけで姓と名が揃っているなら、大きいほうの空白は段の切れ目。
    #
    #     回山山口   高橋 佳広     ← 左はロゴの読み崩れ（実テスト 29枚目）
    #
    # 氏名の空白は姓と名のあいだの1か所だけで、二重にはならない。
    # `オロブスキー    スタニスラフ` は片側だけでは氏名にならないので、
    # これまでどおり切らない。
    #
    # 字づめが広いと**姓の中の字と字も空いて読まれる**（`高 岡   徹`）。
    # これは姓と名の並びではないので、両側が2文字以上のときだけ数える。
    return not any(_is_a_whole_name_by_itself(part) for part in parts)


def _is_a_whole_name_by_itself(part: str) -> bool:
    """その断片だけで姓と名が揃っているか（どちらも2文字以上）。"""
    if not re.search(r"\s", part) or not _looks_like_person_name(part):
        return False
    halves = [half for half in re.split(r"\s+", part.strip()) if half]
    return len(halves) >= 2 and all(len(half) >= 2 for half in halves)


def split_columns(line: str) -> list[str]:
    """左右2段組みの行を、段ごとに分ける（`COLUMN_GAP_RE` の説明を参照）。

    段が1つしか無い行はそのまま返す。

    **行全体が氏名として読めるなら切らない。** 名刺は姓と名のあいだを大きく
    空けて印字することが多く（`オロブスキー    スタニスラフ`・`迎　　　亮一`）、
    その空白は段組みの見分けと同じ形をしている。切ると氏名が半分になり、
    残った `オロブスキー` をさらに姓と名に分けて 姓『オロ』名『ブスキー』に
    なっていた（実テスト 20枚目）。

    2段組みの行はここに当たらない。右段に連絡先や社名が来るため、行全体が
    氏名の形にならない（`Sangeon Lee   T +82.2.6421.7777` は数字を含む）。
    """

    parts = [part.strip() for part in COLUMN_GAP_RE.split(line.strip())]
    if _looks_like_person_name(line) and _name_halves_are_whole(parts):
        return [line.strip()]
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


def spaced_prefix(spaced: str, count: int) -> str:
    """空白を残した行から、先頭 count 文字（空白を数えない）を取り出す。

    `spaced_suffix` の裏返し。氏名が先、役職が後ろの行で氏名側を取り直す。
    """
    taken = 0
    for index, character in enumerate(spaced):
        if character.isspace():
            continue
        taken += 1
        if taken == count:
            return spaced[: index + 1].strip()
    return spaced.strip()


# 氏名と役職のあいだに置かれる区切り。OCRでは落ちたり別の字になったりする。
_ROLE_SEPARATORS = " \t・･·|｜/／-–—,、"


def split_name_before_role(line: str, email: str = "") -> tuple[str, str] | None:
    """`Alex Kudishov ▪ Executive Producer` を氏名と役職に分ける。

    役職の語のうち**いちばん前**にあるものから後ろを役職とする。`Executive
    Producer` のように役職が2語のとき、後ろの語だけを見ると `Executive` が
    氏名側に残る。

    前が氏名らしくなければ何も返さない（役職だけの行を壊さないため）。

    分けるのは**英字で、語が分かれている**氏名に限る。日本語の役職は
    修飾語を前に付けて1語で書くため（`シニアエンジニア` `担当部長`）、
    同じ規則を当てると前半を氏名にしてしまう。実際に切ってしまい、
    既存のテスト2件で捕まえた。
    """
    positions = [line.find(word) for word in TITLE_KEYWORDS if word in line]
    if not positions:
        return None
    start = min(positions)
    name_part = line[:start].strip(_ROLE_SEPARATORS)
    role = line[start:].strip(_ROLE_SEPARATORS)
    if not name_part or not role:
        return None
    if _has_japanese(name_part) or not re.search(r"\s", name_part):
        return None
    if not _looks_like_person_name(name_part, email):
        return None
    return name_part, role


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


# 海外の郵便番号。日本の形（3桁-4桁）が取れなかったときだけ見る。
#
# 実データ 8枚目（韓国）の `06267` は単独の行にあり、日本の形と違うため
# 郵便番号にならないうえ、英字の住所の折り返しとしてつながれて
# `... Seoul, Korea, 06267` になっていた。
#
# **数字だけの行**に限る。5〜6桁だけを見るのは、4桁だと年号・部屋番号と
# 見分けが付かないため（豪州・デンマーク等の4桁は取れない）。7桁を外すのは、
# 日本の郵便番号をハイフン無しで書いた形と紛れるため。誤った番号を入れるより
# 空欄のほうがよい（空欄なら入力する人が気づく）。
FOREIGN_POSTAL_RE = re.compile(r"^\d{5,6}$")

# ハイフンの代わりに空白で刷られた（読まれた）郵便番号。実テスト24枚目は
# `〒151-0053` と刷られているのに `151 0053` と読まれ、空欄になっていた。
#
# **行全体がこの形のときだけ**採る。ゆるめると `TEL 03-7161-2135` の一部を
# 郵便番号にしてしまう類の誤りに戻る（`POSTAL_RE` の上の説明を参照）。
# 電話番号は塊が3つ以上あるので（`090 8587 7873`）、行全体という条件で外れる。
SPACED_POSTAL_RE = re.compile(r"^(\d{3})\s(\d{4})$")


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


# 読み違えられた都道府県の字。実テスト34枚目（ITAKO）で `東京都新宿区` が
# `東京者新宿区` と読まれていた。`者` と `都` は形が近い。
#
# **`東京都` だけを直す。** 都を使う自治体は東京だけなので、`東京者` が正しい
# 語である可能性は無い。他の字（県→懸 など）はここに足さない——実際に見た
# 誤りだけを直す。当てずっぽうで足すと、正しい住所を壊す側に回る。
MISREAD_PREFECTURE = ((("東京者"), "東京都"),)


def repair_address_symbols(text: str) -> str:
    for wrong, right in MISREAD_PREFECTURE:
        text = text.replace(wrong, right)
    return ADDRESS_AT_RE.sub("-", text)


def is_house_number_only(text: str) -> bool:
    """番地だけの行か（`7-18` `1-2-3`）。住所の続きとしてつなぐ判定に使う。

    電話番号・郵便番号を巻き込まないこと。どちらも数字と区切りだけの行に
    なりうる。電話番号は9桁以上（このファイルの他の判定と同じ基準）、
    郵便番号は3桁-4桁なので、その形は除く。
    """
    compact = re.sub(r"\s+", "", normalize(text))
    if not re.fullmatch(r"\d{1,4}(?:-\d{1,4}){0,3}", compact):
        return False
    if re.fullmatch(r"\d{3}-\d{4}", compact):
        return False  # 郵便番号
    return len(re.sub(r"\D", "", compact)) <= 8


# 建物を示す語。住所の続きとして次の行につながるかの判定に使う。
BUILDING_KEYWORDS = (
    "ビル",
    "ビルヂング",
    "ビルディング",
    "タワー",
    "センター",
    "プラザ",
    "ハイツ",
    "コーポ",
    "マンション",
    "レジデンス",
    "アパート",
    "ハウス",
    "館",
)

# 階数の書き方。`8F` `3階` `B1F`。
FLOOR_RE = re.compile(r"(?:^|[\s\d])[Bb]?\d{1,3}\s*(?:[FfＦ]\b|階)")


def is_building_line(text: str) -> bool:
    """建物名・階数だけの行か。住所の続きとしてつなぐ判定に使う。

    日本の名刺では住所が2行に分かれる。

        東京都渋谷区恵比寿南1-1-1
        ヒューマックス恵比寿ビル8F     ← これ

    日本語の住所は行末に読点が無いため「次へ続く」印が無く、英字の住所用の
    つなぎも番地だけの行のつなぎも当たらない（実テスト 9枚目）。

    **会社名を巻き込まないこと。** 巻き込むと住所に社名が入るうえ、会社名の
    判定からもその行が消えて両方が壊れる。連絡先（電話・メール・URL）も同じ。
    """
    line = normalize(text).strip()
    if not line or has_company_keyword(line):
        return False
    if "@" in line or URL_RE.search(for_web_match(line)):
        return False
    if len(re.sub(r"\D", "", line)) >= 9:  # 電話番号（他の判定と同じ基準）
        return False
    if POSTAL_RE.search(line):
        return False
    return any(word in line for word in BUILDING_KEYWORDS) or bool(FLOOR_RE.search(line))


# 2行に分かれた氏名の1語ぶん。先頭が大文字で、残りは小文字。
# 全大文字（`ACME` `SOLUTIONS`）は社名の形なので外す。
NAME_WORD_RE = re.compile(r"^[A-ZÀ-Þ][a-zà-ÿ'’\-]{1,19}$")

# 行政区画の接尾辞。住所にしか出てこない（`Gyeonggi-do` `Chiyoda-ku`
# `Bundang-gu` `Seongnam-si` `Bundang-ro`）。
#
# 氏名の判定で読点を許したところ、`Gyeonggi-do, Republic ofKorea` が
# 姓『Gyeonggi-do』名『Republic ofKorea』になっていた（実テスト 20枚目）。
# ハイフンそのものは氏名にもあるので（`Smith-Jones`）、接尾辞で見分ける。
ADMIN_DIVISION_RE = re.compile(
    r"[A-Za-z]-(?:do|ku|gu|si|shi|ro|dong|cho|machi|ken|fu|gun)\b", re.IGNORECASE
)

# 氏名を探す範囲。名刺の上部に限る（下のほうの語を氏名にしないため）。
NAME_PAIR_SEARCH_LINES = 5


def name_over_two_lines(lines: list[str], used: set[int]) -> tuple[int, str, str] | None:
    """続いた2行が2行に分かれた氏名なら `(先頭の行, 名, 姓)` を返す。

    大きな活字の名刺では姓と名が別の行になる（`German` / `Kurnikov`
    実テスト 10枚目）。1行1語なので、1行を氏名として見る規則には当たらない。

    社名も1語ずつ2行になることがあるため、条件を絞る。**残る危険**は
    `Acme` `Solutions` のように大文字小文字の形が氏名と同じ社名で、これは
    形だけでは見分けられない。緩めるときは実データで確かめること。
    """
    for index in range(min(len(lines) - 1, NAME_PAIR_SEARCH_LINES)):
        if index in used or index + 1 in used:
            continue
        first = normalize(lines[index]).strip()
        second = normalize(lines[index + 1]).strip()
        if not (NAME_WORD_RE.match(first) and NAME_WORD_RE.match(second)):
            continue
        if has_company_keyword(first) or has_company_keyword(second):
            continue
        lowered = f"{first} {second}".lower()
        if has_not_a_name_word(lowered):
            continue
        return index, first, second
    return None


# 住所に出ない記号。これがあれば読み崩れ。
NEVER_IN_ADDRESS_RE = re.compile(r"[=〕〔｜|\\_＝＿]")

# 語の途中で小文字から大文字へ跳ぶ並び（`bEOO` `YfE` `szEZ`）。
CASE_JUMP_RE = re.compile(r"[a-z][A-Z]")


def looks_like_broken_text(text: str) -> bool:
    """読み崩れの断片か。

    目印は2つ。

    - 住所に出ない記号（`=` `〕` `_` `|`）
    - 語の途中で小文字から大文字へ跳ぶ並び。実在の綴り（`McDonald`）でも
      起こるので、**2回以上**を条件にする
    """
    if NEVER_IN_ADDRESS_RE.search(text):
        return True
    return len(CASE_JUMP_RE.findall(text)) >= 2


def looks_like_address(text: str) -> bool:
    """住所には地名が要る。

    弾くのは、漢字もカタカナも英単語も無いもの——数字・記号・ひらがなだけの
    断片。日本の住所は必ず漢字（東京都）かカタカナ（ヒューマックス）を含み、
    海外の住所は英単語を含む。ひらがなだけの住所は無い。

    読み崩れの断片も弾く（`looks_like_broken_text` を参照）。実テスト 25枚目
    （縦書き）では `bEOO-SEI= YfEと szEZ:i〕E7fとEr_井子_料` が入っていた。
    `井` `子` `料` が散らばっているだけで「漢字が2つ以上」を満たしていた。
    """
    if looks_like_broken_text(text):
        return False
    if len(ADDRESS_WORD_RE.findall(text)) >= 2:
        # 英字だけの断片は、語数だけでは住所と見分けられない（実テスト
        # 25枚目の `soipms OOWVN IVQNV8`）。**番地か区切りの読点**を求める。
        # 実データの海外住所はどれも読点を含む。
        #
        #     8F, First Tower, 55, Bundang-ro, ...
        #     2621, Nambusunhwan-ro, Gangnam-gu, Seoul, Korea
        #     Santa Beatriz 111 of 1008, Providencia. Santiago de Chile
        if re.search(r"[,、，]", text) or re.search(r"\d{2,}", text):
            return True
        return False
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


# 日本の番号の国際表記。`+81` のあとの区切りごと `0` に置き換える。
# `(0)`（国内でかけるときだけ 0 を付ける、という慣習表記）も一緒に落とす。
JP_INTERNATIONAL_RE = re.compile(r"^\+\s*81[\s\-.]*(?:\(\s*0\s*\)[\s\-.]*)?")


def to_domestic_form(value: str) -> str:
    """日本の番号が国際表記なら国内表記に直す。それ以外はそのまま返す。

    実テスト 9枚目の名刺には `+81-70-1508-9897` と印字されており、利用者が
    正解として入力したのは `070-1508-9897` だった。同じ番号なので、印字の
    ままにする理由がない。区切り（ハイフン・空白）は印字どおりに残す。

    **他国の番号は直さない。** 国番号を落として 0 を付けるのは日本の規則で、
    韓国の `+82-10-3661-0778`（実テスト 8枚目）に当てはめると別の番号になる。
    """
    replaced, count = JP_INTERNATIONAL_RE.subn("0", normalize(value).strip())
    return replaced if count else value


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
    """かなだけの行か。長音記号（ー）だけの飾り罫は含めない。"""
    stripped = re.sub(r"\s+", "", text)
    if not (stripped and re.fullmatch(r"[ぁ-んァ-ヶー]+", stripped)):
        return False
    return bool(re.search(r"[ぁ-んァ-ヶ]", stripped))


def _is_hiragana_only(text: str) -> bool:
    """ふりがなの行かを判定する。

    ふりがなはひらがなで印字される。カタカナだけの行を「ふりがな」と見ると、
    外国名の名刺（`パトリシオ　バスケス`）で氏名が空になり、ふりがな欄に
    氏名が入る。実データで発生した。

    長音記号（ー）だけの行はふりがなではない。実データでは飾り罫が `ーー` と
    読まれ、それがふりがなに入っていた。かなが1文字も無いものは除く。
    """
    stripped = re.sub(r"\s+", "", text)
    if not re.fullmatch(r"[ぁ-んー]+", stripped or "-"):
        return False
    return bool(re.search(r"[ぁ-ん]", stripped))


def _is_katakana_only(text: str) -> bool:
    stripped = re.sub(r"\s+", "", text)
    return bool(stripped) and bool(re.fullmatch(r"[ァ-ヶー・]+", stripped))


def _has_japanese(text: str) -> bool:
    return bool(re.search(r"[ぁ-んァ-ヶ一-龥]", text))


def _email_words(email: str) -> set[str]:
    """メールアドレスの左側にある語。氏名の裏づけに使う。"""
    local = email.split("@", 1)[0].lower()
    return set(re.findall(r"[a-z]{2,}", local))


def _looks_like_person_name(line: str, email: str = "") -> bool:
    text = re.sub(r"\s+", "", normalize(line))
    if len(text) < 2:
        return False
    # 長さの上限は字種で変える。日本語の氏名は長くて12文字ほどだが、ラテン文字
    # の氏名はもっと長い（実データの `ANA FERNANDEZ DEL RIO` は空白を除いて
    # 18文字あり、12文字で切っていたため氏名が空になっていた）。
    if len(text) > (12 if _has_japanese(text) else 32):
        return False
    # 漢字だけの行には、さらに短い上限を置く。
    #
    # 12文字という上限は、かなで書く外国名（`オロブスキー スタニスラフ`）に
    # 合わせたもの。漢字の氏名はそこまで長くならない。姓は最長でも5文字
    # （`勘解由小路` `左衛門三郎`）で、実際に多いのは4文字まで（`小比類巻`
    # `勅使河原`）。名を足しても8文字を超えることはまず無い。
    #
    # 空いた4文字ぶんに職名が入っていた。実テスト19枚目（沖縄労働局）:
    #
    #     印字        需給調整事業専門相談員
    #     tesseract   需給 調整 事業 専門 相談      ← 末尾の「員」が落ちる
    #     → 姓『需給調整事業』／名『専門相談』
    #
    # 「員」が読めていれば役職の語尾（`TITLE_TAIL_WORDS`）で弾けたが、
    # 1文字落ちただけで氏名になっていた。**姓が6文字の日本人はいない**ので、
    # 語に頼らず長さで断てる。
    #
    # かなを1文字でも含む行はこの上限を使わない（`オロブスキー` のような
    # 音写の氏名を巻き添えにしないため）。
    if len(text) > MAX_KANJI_NAME and KANJI_ONLY_RE.fullmatch(text):
        return False
    if any(keyword in line for keyword in COMPANY_KEYWORDS + TITLE_KEYWORDS + DEPARTMENT_KEYWORDS):
        return False
    if any(word in text for word in NOT_A_NAME_WORDS_JA):
        return False
    if re.search(r"\d", text):
        return False
    # 役職の字が残っている行は氏名ではない。実テスト34枚目（ITAKO）で、
    # 印字の `代表取締役` が EasyOCR に `代千取橋役` と読まれ、姓『代千』／
    # 名『取橋役』になっていた。tesseract は同じ名刺の `河野 修 弘` を正しく
    # 読めていたのに、**併合はエンジンごとの埋まり具合で選ぶため同数で並び、
    # 先の EasyOCR が勝っていた**。ここで弾けば、正しいほうが残る。
    #
    # `締` は氏名に出ない字なので、どこにあっても弾く。
    # `役` は**末尾のときだけ**弾く。`役所`（役所広司）のように先頭に来る姓が
    # 実在するので、どこでも弾くと本物の氏名を巻き添えにする。
    if "締" in text or text.endswith("役"):
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
    # かなだけの行にひらがなが混じっていれば、読み崩れであって氏名ではない。
    #
    # かなの氏名は外国名の音写なのでカタカナで印字される（`ユン ソクン`
    # `パトリシオ バスケス`）。ひらがなだけの行は、ふりがなとして別に扱う。
    # 実データ 10枚目（ロシアの名刺）では、飾りが `に ロニ エニ` と読まれ、
    # 姓『にロニ』名『エニ』として登録されていた。空欄なら入力する人が
    # 気づくが、それらしい誤りは気づかれずに保存される。
    if _is_kana_only(text) and re.search(r"[ぁ-ん]", text) and re.search(r"[ァ-ヴ]", text):
        return False
    # 漢字とカタカナが何度も入れ替わる行は、ロゴなどの読み崩れ。
    #
    # 日本語の氏名で字種が変わるのは1回まで（`ジョンソン裕子`）。実データ
    # 17枚目では、ロゴ `METEORISE` が `小ケ戸テンク南ア三` と読まれ、
    # 姓『小ケ』／ 名『戸テンク南ア三』になっていた。
    #
    # ひらがなは数えない（`山田はな子` は氏名）。`小ケ戸` のような、かなを
    # 含む珍しい姓を残すため、3つまでは通す。
    if len(re.findall(r"[一-龥々〆]+|[ァ-ヴ]+", re.sub(r"[ぁ-んー・]", "", text))) > 3:
        return False
    # 々（踊り字）を入れておくこと。`佐々木` `野々村` は珍しくない姓で、
    # 入れないと氏名として認識されない（実測で `主任 佐々木 健` の氏名が空になった）。
    if re.fullmatch(r"[一-龥々〆ヶヵぁ-んァ-ヴー・]{2,12}", text):
        # 長音記号や中黒だけの行は飾り罫。実データでは `ーー` を氏名として
        # 登録していた。字が1文字も無いものは氏名にしない。
        #
        # 字が1文字しか無いものも同じ（実データ 10枚目の `スー`）。氏名は
        # 2文字以上あるので、飾りを除いて1文字なら読み崩れとみなす。
        # `リー` のような1文字＋長音の姓は落ちるが、名刺は姓と名を並べて
        # 印字するため、行がそれだけになることはまず無い。
        return len(re.findall(r"[一-龥々〆ヶヵぁ-んァ-ヴ]", text)) >= 2
    latin = normalize(line).strip()
    # 語数の上限は4。スペイン語圏の氏名は父方・母方の姓を並べるため長い
    # （実データ: `ANA FERNANDEZ DEL RIO`）。3語までにしていて空になっていた。
    # 最初の語の直後の読点だけ許す（`Jeong, Sun Ho` 実テスト 23枚目）。
    if not re.fullmatch(
        r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ.\-]*,?(?:\s+[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ.\-]*){1,3}", latin
    ):
        return False
    # 行政区画の接尾辞があれば住所の行。読点を許したことで
    # `Gyeonggi-do, Republic ofKorea` が氏名になっていた（実テスト 20枚目）。
    if ADMIN_DIVISION_RE.search(latin):
        return False
    lowered = latin.lower()
    if has_not_a_name_word(lowered):
        return False
    # 印字された氏名は先頭が大文字（`German Kurnikov` `SEOKHOON YOON`）。
    # 小文字で始まるものは読み崩れの断片。実データ 10枚目では、メールの行の
    # 残りかす `ee BO` を 姓『BO』名『ee』として登録していた。
    #
    # 2語目以降は見ない。`Maria de la Cruz` のように小文字で始まる語を
    # 含む氏名があるため。
    if not latin[:1].isupper():
        return False
    if latin != latin.upper():
        return True
    # 全部大文字はロゴや社名の綴り（`AONE GAMES`）のことが多い。ただし海外の
    # 名刺は氏名も大文字で刷る。メールの左側にその語があれば人名とみなす。
    #
    #   `ana@causalfoundry.ai`   と `ANA FERNANDEZ DEL RIO` → 氏名
    words = {word.lower() for word in latin.split()}
    if words & _email_words(email):
        return True
    # メールが無ければ裏づけが取れない。推測で氏名にはしない。
    if "@" not in email:
        return False
    # メールの左側が役職名（`ceo@` `info@`）だと、上の照合はできない。
    # そこでドメインを見る。社名はドメインの綴りになっていることが多いので、
    # 行の語がすべてドメインに現れるなら社名、現れないなら人名とみなす。
    #
    #   `patricio@aonegames.com` と `AONE GAMES`    → aonegames に両方ある → 社名
    #   `ceo@omorobot.com`       と `SEOKHOON YOON` → omorobot に無い     → 氏名
    domain = email.split("@", 1)[1].lower()
    return not all(word in domain for word in words)


# 韓国の姓のローマ字表記。**姓が先に印字されているか**を見分けるためだけに使う。
#
# 実テスト 21枚目の `Yeo Seunghwan` は 姓『Seunghwan』名『Yeo』と逆になって
# いた。英字の氏名は「名 姓」の順として扱っているが、韓国の名刺はどちらの
# 並びもあり、形だけでは決められない（8枚目は `Sangeon Lee` で姓が後ろ）。
#
# **西洋の人名と紛れる語は入れないこと。** `Kim`・`Lee`・`Park`・`Han`・
# `Song`・`Oh` は英語圏の人名にもあるため、入れると `Kim Anderson` の姓が
# `Kim` になる。姓が後ろにある書き方は今までどおりの規則で正しく取れるので、
# 語彙に入れる必要もない。
KOREAN_SURNAMES = frozenset(
    {
        "yeo", "choi", "hwang", "kwon", "jeong", "jung", "chung", "baek",
        "byun", "ryu", "shim", "sohn", "yoon", "yun", "jang", "jeon",
        "kang", "kwak", "gwak", "noh", "paik", "pyo", "hyun", "seok",
        "shin", "joo", "nam",
    }
)


def split_person_name(full: str) -> tuple[str, str]:
    """姓と名に分割する。空白があればそこで、なければ日本語姓の一般的な長さで分ける。"""
    text = normalize(full)
    parts = [p for p in re.split(r"[\s　]+", text) if p]
    if len(parts) >= 3 and _has_japanese(text):
        # かなの氏名・ふりがなは、OCRが語の途中にも空白を入れる。実測では
        #
        #   `やまだ たろう`      → `や まだ た ろう`   → `や` / `まだ た ろう`
        #   `すずき いちろう`    → `すず き いち ろう` → `すず` / `き いち ろう`
        #   `パトリシオ バスケス` → `パト リシオ バスケス` → `パト` / `リシオ バスケス`
        #
        # のように先頭の空白で切っていた（合成サンプル16枚のうち9枚でふりがなが不一致）。
        # どこが語の切れ目かは字面では決まらないので、長さの釣り合いが
        # いちばん良い位置で分ける（姓と名は極端に長さが違わない）。
        #
        # 漢字の氏名も同じ。名刺は字間を大きく空けて刷ることがあり、実データ
        # 18枚目の `舟　木　香　織` は1文字ずつに分かれて読まれて
        # 姓『舟』／ 名『木 香 織』になっていた。
        #
        # 釣り合いが同じなら、後ろで切る（`冨 田 修` は 冨田／修）。
        # 日本語の姓は2文字が最も多い。
        best = min(
            range(1, len(parts)),
            key=lambda at: (abs(len("".join(parts[:at])) - len("".join(parts[at:]))), -at),
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
        # ラテン文字の氏名は「名 姓」の順で印字される。実データ（7枚目）の
        # `Sangeon Lee` を、日本語と同じ「姓 名」とみて 姓=Sangeon としていた。
        # 姓は最後の語。残りを名にする。
        if not _has_japanese(text) and re.fullmatch(r"[A-Za-zÀ-ÿ ,.'\-]+", text):
            # 読点で区切られていれば、その前が姓（`Jeong, Sun Ho` 実テスト 23枚目）。
            # 言語を問わない書き方なので、いちばん確かな手がかり。
            head, comma, tail = text.partition(",")
            if comma and head.strip() and tail.strip():
                return head.strip(), " ".join(tail.split())
            # 韓国の名刺は姓が先のこともある（`Yeo Seunghwan` 実テスト 21枚目）。
            # 姓が後ろの書き方（`Sangeon Lee` 実テスト 8枚目）と形は同じなので、
            # 韓国の姓の語が**前にあるとき**だけ入れ替える。
            if (
                len(parts) == 2
                and parts[0].lower() in KOREAN_SURNAMES
                and parts[1].lower() not in KOREAN_SURNAMES
            ):
                return parts[0], parts[1]
            given = [parts[0]]
            rest = list(parts[1:])
            # `John A. Smith` の `A.` は中間名の頭文字。名のほうに残す。
            while rest and re.fullmatch(r"[A-Za-zÀ-ÿ]\.?", rest[0]):
                given.append(rest.pop(0))
            # 残り全部が姓。スペイン語圏は父方・母方の姓を並べるため複数語に
            # なる（実データ: `ANA FERNANDEZ DEL RIO` の姓は `FERNANDEZ DEL RIO`）。
            if rest:
                return " ".join(rest), " ".join(given)
            return parts[-1], " ".join(parts[:-1])
        return parts[0], " ".join(parts[1:])
    if len(text) >= 4 and _has_japanese(text):
        return text[:2], text[2:]
    if len(text) == 3 and _has_japanese(text):
        return text[:2], text[2:]
    return text, ""


# 名に多く、姓にはまず出ない語尾。ローマ字の姓名の並びを決めるのに使う。
#
#   ろう  太郎 Taro／一郎 Ichiro／信一郎 Shinichiro／健太郎 Kentaro
#   こ    花子 Hanako／美智子 Michiko
#   すけ  大輔 Daisuke／龍之介 Ryunosuke
#
# 姓の語尾と衝突するものは外す。`城`（Miyashiro 宮城）と `黒`（Ishiguro
# 石黒・Meguro 目黒）は、どちらも `ro` で終わる**姓**の作りである。
_GIVEN_NAME_TAILS = ("ro", "ko", "suke")
_SURNAME_TAILS_IN_RO = ("shiro", "guro", "kuro")

# これより短い語では語尾を手がかりにしない（`Ko` だけの語など）。
_MIN_TAIL_LENGTH = 4


def _is_given_name(word: str) -> bool:
    """その語が名らしいか。語尾だけで見る。"""
    low = word.lower()
    if len(low) < _MIN_TAIL_LENGTH or not low.endswith(_GIVEN_NAME_TAILS):
        return False
    return not low.endswith(_SURNAME_TAILS_IN_RO)


def _order_by_given_name(last: str, first: str, last_kana: str, first_kana: str):
    """ローマ字の姓名の並びを、名らしい語尾から決める。

    **名刺のローマ字は、姓が先のものと名が先のものが両方ある。**

        木村 央志                笠間　信一郎
        Nakaji Kimura   ← 名 姓   Kasama Shinichiro   ← 姓 名

    綴りだけでは、どちらが姓かは分からない。`split_person_name` は最後の語を
    姓とするので、`Kasama Shinichiro` では姓と名が入れ替わる。**並びを
    取り違えると2欄とも誤る**ので、長音が落ちて1欄が惜しいのとは重さが違う。

    字数と拍数の釣り合いで決めようとしたが、これは**使えなかった**。
    長音が落ちるため `信一郎` は `Shinichiro`→`しにちろ`（4拍）に縮み、
    `笠間`＝`かさま`（3拍）とほとんど並ぶ。頼りにした差が、名刺に刷られる
    時点で消えている。

    語尾のほうが残る。`ろう`（太郎・一郎・信一郎）と `こ`（花子）と
    `すけ`（大輔）は名に多く、姓にはまず出ない。片方だけが名らしいときに
    限って、そちらを名とする。両方・どちらでもないときは決めない
    （`Nakaji Kimura` は決まらず、今までどおり最後の語を姓とする）。
    """
    if _is_given_name(first) and not _is_given_name(last):
        # 最後の語が姓――今までどおり。
        return last_kana, first_kana
    if _is_given_name(last) and not _is_given_name(first):
        return first_kana, last_kana
    return last_kana, first_kana


def _fill_kana_from_romaji(
    fields: dict[str, Any],
    confidence: dict[str, float],
    lines: list[str],
    spaced_lines: list[str],
    used: set[int],
    name_index: int | None,
) -> None:
    """氏名の脇に刷られたローマ字を、ふりがなにする。

    日本の名刺は、ふりがなの位置にローマ字を刷ることが多い。

        木村 央志
        Nakaji Kimura          ← ふりがなの位置

    ここまでの処理は「ひらがなだけの行」からしかふりがなを取らないので、
    この形の名刺はふりがなが空欄のままだった。実テスト（223枚）ではこの
    形が多く、そのぶんがすべて手入力になっていた。

    変換そのものは `services/ocr/romaji` にある。長音が落ちて刷られるため
    素朴な変換の実測は74%で、外れるのは 佐藤（さと）・太郎（たろ）のような
    **漢字を見れば読みが分かる**名前。当たるのは 央志＝なかじ のような
    **ローマ字が唯一の手がかり**である珍しい読み。画面では未確認（黄色）で
    出るので、誤りは気づける側に寄る。

    **漢字かなの氏名が取れているときだけ掛ける。** ローマ字の変換は
    `Mike`（みけ）`Kate`（かて）のような英語名も通してしまう。外国名の
    名刺（`Patricio Vasquez` `German Kurnikov`）でふりがなを埋めると、
    読みでない綴りが登録される。同じ名刺に漢字かなの氏名があることが、
    そのローマ字が日本語の音写である証拠になる。

    確度は 0.5。印字されたふりがな（0.7）より弱い——読み取った文字では
    なく、そこから導いたものなので。
    """
    if not _has_japanese(f"{fields['last_name']}{fields['first_name']}"):
        return

    found: list[tuple[int, int, str, str]] = []
    for index, line in enumerate(lines):
        if index in used or _has_japanese(line):
            continue
        if not _looks_like_person_name(line, fields["email"]):
            continue
        # 姓は最後の語（`split_person_name` を参照）。`Nakaji Kimura` は
        # 姓=Kimura・名=Nakaji で、漢字の 木村／央志 と並びが逆になる。
        last, first = split_person_name(spaced_lines[index])
        last_kana, first_kana = name_to_hiragana(last), name_to_hiragana(first)
        if last_kana and first_kana:
            last_kana, first_kana = _order_by_given_name(last, first, last_kana, first_kana)
        # 片方だけ入れない。姓と名がずれたふりがなは、空欄より悪い。
        if not last_kana or not first_kana:
            continue
        away = abs(index - name_index) if name_index is not None else index
        found.append((away, index, last_kana, first_kana))

    if not found:
        return
    # 氏名の行にいちばん近いものを採る。
    #
    # **地名は綴りでは弾けない。** `Shibuya Tokyo` も日本語のローマ字なので
    # きれいに変換でき、しぶや／ときょ がふりがなに入っていた。語彙で弾く
    # 手も使えない——千葉・足立・太田・中野・目黒・荒川・品川は、どれも
    # 区名であると同時に実在の姓で、落とせば本物の氏名を巻き添えにする。
    #
    # 位置で分けるしかない。ローマ字の氏名は氏名の脇に刷られ、住所の断片は
    # 住所の塊の中にある。実テスト24枚目では氏名の4行あと（読み取りの行の
    # 順番は印字の順番と違うので、隣とは限らない）。
    #
    # これでも住所の断片が氏名のすぐ脇に来れば入る。画面では未確認（黄色）
    # で出るので直せるが、**取りこぼしではなく誤りとして残る**ことは承知
    # のうえで採っている。
    _, index, last_kana, first_kana = min(found)
    fields["last_name_kana"], fields["first_name_kana"] = last_kana, first_kana
    confidence["last_name_kana"] = 0.5
    used.add(index)


def parse_fields(lines: list[str]) -> dict[str, Any]:
    """OCRの行リストから名刺項目を抽出する。"""
    # spaced: 空白を残したまま正規化した行。氏名・ふりがなの分割に使う。
    # cleaned: さらに字間の空白を除いた行。ラベル照合や語の判定に使う。
    pairs = []
    for raw in lines:
        for line in split_columns(raw):
            line = strip_leading_noise(normalize(line))
            spaced = join_spaced_letters(line).strip()
            compact = strip_inner_spaces(line)
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
        # そのラベルが受け持った番号の数。1つのラベルで2つ並べる名刺がある
        # （`TEL 03-1234-5678 / 090-1234-5678`）。ラベルが指しているのは
        # 最初の1つだけなので、2つ目からは番号の形で見分ける。
        taken: dict[int, int] = {}

        for match in matches:
            number = to_domestic_form(match.group(0).strip(" \t-ー－."))
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
                taken[position] = taken.get(position, 0) + 1
                if taken[position] > 1 and digits[:3] in MOBILE_PREFIXES:
                    # このラベルはもう前の番号に使われている。2つ目以降は
                    # 番号の形で見分ける。
                    kind = "mobile"
                    score = 0.7
                # **印字されたラベルを、番号の形より先に見る。**
                #
                # 090・080・070 は携帯に割り当てられた番号だが、名刺に
                # `TEL 070-9338-4365` と刷ってあれば電話である（実テスト
                # 21枚目）。番号の形でラベルを覆すと、名刺のとおりに登録
                # できず、入力する人が毎回入れ替えることになる。
                #
                # 20枚目の `PHONE 携帯 070 4100 5747` は `携帯` が `捕帯` と
                # 読まれてラベルにならず、残った `PHONE` を信じていた。
                # そちらは `帯` もラベルとして見ることで直している
                # （`MOBILE_LABELS` を参照）。ラベルの読み落としは、
                # ラベルの側で直すのが筋。
            if not fields[kind]:
                fields[kind] = number
                confidence[kind] = score
            used.add(index)
            phone_used.add(index)

    # 郵便番号・住所
    # 採った行を覚えておく。番地が次の行へ回ることがあり、つなぐのに要る。
    address_index: int | None = None
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
                address_index = index
            used.add(index)

    # 日本の形が、空白で区切られて読まれた場合。
    if not fields["postal_code"]:
        for index, line in enumerate(cleaned):
            if index in used:
                continue
            match = SPACED_POSTAL_RE.match(line.strip())
            if match:
                fields["postal_code"] = f"{match.group(1)}-{match.group(2)}"
                # ハイフンのもの（0.95）より弱い。区切りが読めていないため。
                confidence["postal_code"] = 0.7
                used.add(index)
                break

    # 日本の形が取れなかった場合の、海外の郵便番号。
    #
    # 住所を組み立てる前に済ませること。英字の住所は行末の読点で「次へ続く」と
    # 判断してつなぐため（`wrapped_blocks`）、先に印を付けておかないと
    # `Korea,` の次にある `06267` まで住所に入る（実データ 8枚目）。
    if not fields["postal_code"]:
        for index, line in enumerate(cleaned):
            if index in used:
                continue
            if FOREIGN_POSTAL_RE.match(line.strip()):
                fields["postal_code"] = line.strip()
                # 日本の形（0.95）より弱い根拠。数字の並びだけで決めているため。
                confidence["postal_code"] = 0.6
                used.add(index)
                break

    if not fields["address"]:
        for index, line in enumerate(cleaned):
            if index in used:
                continue
            if len(line) >= 6 and sum(hint in line for hint in ADDRESS_HINTS) >= 2:
                fields["address"] = strip_postal_prefix(strip_address_label(line))
                confidence["address"] = 0.6
                address_index = index
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
                address_index = index
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
            address_index = end
            used.update(range(start, end + 1))

    # 英字の住所が折り返された場合、前の行をつなぐ。
    #
    #     VORT Suehiro-cho II 2F, 6-14-3, Sotokanda,     ← 読点で終わる＝続く
    #     Chiyoda-ku, Tokyo 101-0021, JAPAN              ← 郵便番号があるのでこちらを採っていた
    #
    # 郵便番号のある行だけを住所にしていたため、番地とビル名が落ちていた
    # （実データ 17枚目）。英字の住所は折り返しに読点が残る。日本語の住所は
    # 読点で終わらないので、この見分けは英字の住所にだけ効く。
    while address_index is not None and address_index > 0:
        previous = address_index - 1
        if previous in used or not _continues_into_next_line(cleaned[previous]):
            break
        fields["address"] = f"{normalize(cleaned[previous]).strip()} {fields['address']}"
        used.add(previous)
        address_index = previous

    # 住所の先頭に郵便番号が置かれている場合（`125167, Moscow,` 実テスト 10枚目）。
    # 住所を組み立てたあとに見る。組み立て前だと、折り返しでつながる前の
    # 断片しか見えない。
    if not fields["postal_code"] and fields["address"]:
        match = LEADING_POSTAL_RE.match(fields["address"])
        if match:
            fields["postal_code"] = match.group(1)
            confidence["postal_code"] = 0.6
            fields["address"] = fields["address"][match.end() :].strip()

    # 住所の末尾に置かれている場合（`…, Republic of Korea, 13591` 実テスト 23枚目）。
    if not fields["postal_code"] and fields["address"]:
        match = TRAILING_POSTAL_RE.search(fields["address"])
        if match:
            fields["postal_code"] = match.group(1)
            confidence["postal_code"] = 0.6
            fields["address"] = fields["address"][: match.start()].strip()

    # 番地だけが次の行に回った場合につなぐ。
    #
    # 日本語の住所は読点で終わらないので、折り返しの印が無い。実データ
    # （3枚目）では `大阪府松原市高見の里六丁目` と `7-18` が別の行として
    # 読まれ、番地の無い住所になっていた。人が見れば1行に見えるため、
    # 「OCRが弱い」と誤解されやすい種類の取りこぼし。
    while address_index is not None and address_index + 1 < len(cleaned):
        nxt = address_index + 1
        if nxt in used or not is_house_number_only(cleaned[nxt]):
            break
        fields["address"] = f"{fields['address']}{normalize(cleaned[nxt]).strip()}"
        used.add(nxt)
        address_index = nxt

    # 建物名が次の行に回った場合につなぐ（実テスト 9枚目）。
    #
    #     東京都渋谷区恵比寿南1-1-1
    #     ヒューマックス恵比寿ビル8F     ← 番地までしか住所に入っていなかった
    #
    # 1行だけにする。2行以上つなぐと、たまたま建物らしい語を含む別の項目まで
    # 巻き込む。名刺の住所で建物が2行に分かれることはまずない。
    if address_index is not None and address_index + 1 < len(cleaned):
        nxt = address_index + 1
        if nxt not in used and is_building_line(cleaned[nxt]):
            fields["address"] = f"{fields['address']} {normalize(cleaned[nxt]).strip()}"
            used.add(nxt)
            address_index = nxt

    # 会社名
    for index, line in enumerate(cleaned):
        if has_company_keyword(line):
            fields["company_name"] = line
            confidence["company_name"] = 0.9
            used.add(index)
            break
        # 官公庁は法人格の語を持たない。組織名と部署が1行に並ぶので分ける
        # （`沖縄労働局 職業安定部`。`split_office_and_department` を参照）。
        split = split_office_and_department(spaced_lines[index])
        if split is not None:
            fields["company_name"], department = split
            confidence["company_name"] = 0.75
            fields["department_name"] = department
            confidence["department_name"] = 0.75
            used.add(index)
            # 官公庁も階層を行で分けて刷る（`職業安定部` の下に
            # `需給調整事業室`）。並びをたどってつなぐ。
            _, after = _department_run(cleaned, index, used)
            if after:
                fields["department_name"] = " ".join([department, *after])
            break
        # 空白が無く、組織名だけの行。
        if not fields["company_name"] and is_office_name(line):
            fields["company_name"] = line
            confidence["company_name"] = 0.75
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
        # 末尾の区切りを、残りが4文字以上あるあいだ外していく。
        #
        # 以前は2文字の末尾と既知の語（co/com/jp など）だけを外していた。
        # `.tokyo` `.games` のような新しいドメインを知らないため、実データ
        # 18枚目では `kimusubi.tokyo` の鍵が `kimusubitokyo` のままになり、
        # 社名として `kimusubi` ではなくURLの行を採っていた。
        #
        # 語を並べるのはきりが無い（新しいドメインは増え続ける）ので、
        # **形**で外す。会社を表す部分まで削らないよう、6文字までの区切りに
        # 限る（`logi-kyushu.example` の `example` は7文字なので残る）。
        host = domain.lower()
        while "." in host:
            head, _, last = host.rpartition(".")
            if len(head) < 4 or not re.fullmatch(r"[a-z]{2,6}", last):
                break
            host = head
        key = re.sub(r"[^a-z0-9]", "", host)
        if len(key) >= 4:
            # ドメインは社名を縮めることがある（`edgecre` ← `Edge Creators`）ので、
            # 先頭が一致する行も同じ会社と見る。ただし当たるものが2種類ある。
            #
            #   読み崩れた断片   `時NEXO` → `nexo`（鍵 `nexongames` より短い）
            #   URLの行         `kimusubitokyo`（鍵 `kimusubi` より長い）
            #
            # 以前は**いちばん長いもの**を採っていたので、断片は避けられたが
            # URLの行を社名にしていた（実データ 18枚目）。鍵と**字数がいちばん
            # 近いもの**を採ると、どちらも避けられる。
            matches: list[tuple[int, int, str]] = []
            for index, line in enumerate(cleaned):
                if index in used:
                    continue
                candidate = re.sub(r"[^a-z0-9]", "", line.lower())
                if len(candidate) >= 4 and (candidate.startswith(key) or key.startswith(candidate)):
                    matches.append((abs(len(candidate) - len(key)), index, line))
            if matches:
                _, index, line = min(matches)
                fields["company_name"] = drop_unmatched_prefix(line, key)
                confidence["company_name"] = 0.6
                used.add(index)

    # 部署
    for index, line in enumerate(cleaned):
        if index in used or fields["department_name"]:
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
            # 続きの行も部署なら、つなぐ。組織の階層を上から順に刷る名刺が
            # あり、1行しか取らないと**どの部署に属するのか分からなくなる**
            # （実テスト 22枚目は3行のうち最後の1行だけだった）。
            #
            #     Store Business Management Team
            #     Publishing&Platform ESD Business Division
            #     Megaport Division Group
            #
            # 役職の行（`Team Manager`）は巻き込まない。`Team` は部署にも
            # 役職にも出るので、役職の語を含む行で打ち切る。
            before, after = _department_run(cleaned, index, used)
            if before or after:
                fields["department_name"] = " ".join(
                    [*before, fields["department_name"], *after]
                )
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
                    and _looks_like_person_name(tail, fields["email"])
                ):
                    # 「課長補佐」「主任研究員」のような役職の続きと区別する。
                    # 氏名として通すのは3文字以上で、役職の語尾で終わらないものに限る
                    fields["title"] = keyword
                    # 空白を数えない字数で位置を決める（`John Smith` は10文字）
                    letters = len(re.sub(r"\s+", "", tail))
                    title_name = (tail, spaced_suffix(spaced_lines[index], letters))
                elif split := split_name_before_role(candidate, fields["email"]):
                    # 氏名が先、役職が後ろの行（`Alex Kudishov ▪ Executive Producer`）。
                    # 英語の名刺ではこちらが普通で、上の分岐（役職が先）の裏返し。
                    name_part, role = split
                    fields["title"] = role
                    letters = len(re.sub(r"\s+", "", name_part))
                    title_name = (name_part, spaced_prefix(spaced_lines[index], letters))
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
        # 漢字はどれも1文字につき1つ以上のかなで読むので、ふりがなは読む
        # 氏名より短くならない。実データ 19枚目では、ロゴの標語
        # `みらいのために`（7文字）を `霧給調整事業専門相談員`（11文字）の
        # ふりがなとして採り、せい『みら』／ めい『いのために』にしていた。
        if len(line) < len(cleaned[following]):
            continue
        if not _looks_like_person_name(cleaned[following], fields["email"]):
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
        katakana_name: int | None = None
        japanese_name: int | None = None
        for index, line in enumerate(cleaned):
            if index in used or _is_hiragana_only(line):
                continue
            if not _looks_like_person_name(line, fields["email"]):
                continue
            if _has_japanese(line):
                # かなだけの氏名で、姓と名の区切りが無いものは後回しにする。
                # 外国名の音写は同じ名前がラテン文字でも刷られていることが多く、
                # そちらは空白で区切られているぶん確実に割れる。
                #
                #   印字  ユン　ソクン        読み  dy  ソクン
                #         SEOKHOON YOON            SEOKHOON YOON
                #
                # `ユン` が読めず、残った `ソクン` を 姓『ソク』名『ン』に
                # 割っていた（実データ）。区切りが無いなら割る位置は決められない。
                #
                # 区切りが残っていれば、かなのほうが名刺の印字に近いので優先する
                # （`ユン ソクン` `パトリシオ　バスケス`）。空白は cleaned では
                # 消えているため、空白を残した spaced_lines のほうを見る。
                #
                # 漢字の行も同じ。区切りが無ければ姓と名に割る位置は決め
                # られず、`絵師` のような2文字の語は姓だけが埋まって終わる
                # （実テスト 29枚目）。同じ読み取りの中に区切りのある
                # `高橋 佳広` があるなら、そちらを先に見る。
                if not re.search(r"\s", spaced_lines[index]):
                    if katakana_name is None:
                        katakana_name = index
                    continue
                if japanese_name is None:
                    japanese_name = index
                continue
            if ascii_name is None:
                ascii_name = index
        # 日本語の候補があっても、**メールアドレスが英字の候補だけを裏づけて
        # いる**なら英字を採る。汚れや罫線が漢字・カタカナとして読まれ、それが
        # 氏名になっていた（実テスト 4枚目 `心万』『心』／7枚目『巨』『メロ』）。
        # 形だけでは読み崩れと本物の日本語の氏名を見分けられないが、
        # `ana@causalfoundry.ai` `eonlee@nexongames.co.kr` は裏づけになる。
        #
        # 降ろすのは**3文字以下**の候補だけにする。`パトリシオ　バスケス` は
        # ラテン文字と同じ人名の音写で、メールが片方しか裏づけられない
        # （かなとラテン文字は文字が違うため）。長い候補まで降ろすと、
        # 日本語で印字された氏名を捨ててしまう。
        if japanese_name is not None and ascii_name is not None:
            short = len(re.sub(r"\s+", "", cleaned[japanese_name])) <= 3
            backed_ja = email_backs_name(cleaned[japanese_name], fields["email"])
            backed_en = email_backs_name(cleaned[ascii_name], fields["email"])
            if short and backed_en and not backed_ja:
                japanese_name = None
                katakana_name = None

        if name_index is None:
            name_index = japanese_name
        if name_index is None:
            name_index = ascii_name if ascii_name is not None else katakana_name

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
            if _looks_like_person_name(segment, fields["email"]):
                name_index = index
                name_from_segment = segment
                break

    # 和英が併記されている場合、漢字のほうを使う（実テスト 24枚目）。
    #
    #     代表取締役　星 山 孝 明     ← 役職の語を含むので氏名として見つからない
    #     Hoshiyama Takaaki           ← こちらが採られ、姓『Takaaki』になっていた
    #
    # 英字の氏名は「名 姓」の順として扱うが、日本の名刺のローマ字は「姓 名」の
    # 順で書くことが多く、形だけでは決められない。漢字が読めているなら、
    # そちらを使えばよい（英字は補助の表記）。
    if (
        title_name is not None
        and _has_japanese(title_name[1])
        and (name_index is None or not _has_japanese(spaced_lines[name_index]))
    ):
        name_index = None

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

    # 氏名が2行に分かれて印字されている場合（`German` / `Kurnikov` 実テスト 10枚目）。
    # 他のどの規則でも取れなかったときだけ見る。
    if not fields["last_name"] and not fields["first_name"]:
        pair = name_over_two_lines(cleaned, used)
        if pair is not None:
            index, given, family = pair
            fields["first_name"], fields["last_name"] = given, family
            # 1行で読めた氏名（0.7）より弱い根拠。行のつながりだけで決めている。
            confidence["last_name"] = confidence["first_name"] = 0.5
            used.update((index, index + 1))

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
            # 前の行がひらがなの文なら、この行はその文の続きであって
            # ふりがなではない。実データ 19枚目のロゴの標語
            #
            #     ひと、くらし、
            #     みらいのために      ← せい『みら』／ めい『いのために』にしていた
            #
            # 「氏名の行に接していること」を条件にしてはいけない。OCRの行の
            # 順番は印字の順番と違い、合成サンプルでは氏名とふりがなが4行
            # 離れている（実際にこれで試して、ふりがなの正答率が 65%→50% に
            # 落ちた）。見るのは前の行だけにする。
            if index > 0 and _is_hiragana_sentence(cleaned[index - 1]):
                continue
            # 標語の2行は、順番が入れ替わって読まれることがある（実テスト
            # 19枚目では tesseract が逆順に読んでいた）。段組みでも同じことが
            # 起きる（実テスト18枚目）。`、` で終わるひらがなの行はそこで
            # 終わっていない文なので、**その前後のひらがなの行は続き**とみなす。
            if _belongs_to_a_slogan(cleaned, index):
                continue
            last, first = split_person_name(spaced_lines[index])
            # 姓の読みが1文字の氏名は無い。1文字になるのは、ひらがなに見えた
            # 絵柄の読み崩れ（実テスト 29枚目の `だ こう`）。ふりがなが空欄
            # なら入力する人が気づくが、誤った読みは気づかれずに登録される。
            if len(last) < 2:
                continue
            fields["last_name_kana"], fields["first_name_kana"] = last, first
            confidence["last_name_kana"] = 0.7
            used.add(index)
            break

    # ふりがなの位置にローマ字が刷られている名刺。
    if not fields["last_name_kana"] and not fields["first_name_kana"]:
        _fill_kana_from_romaji(fields, confidence, cleaned, spaced_lines, used, name_index)

    # ロゴ・QRコード・飾り罫が英数字1〜4文字として読まれ、項目の前後に付く。
    # 実データでは会社名が `© 沖縄県東京事務所`、住所が
    # `Ob eC F 東京都千代田区平河町2-6-3 Ai AP APE LOBE` になっていた。
    for key in ("company_name", "department_name", "title", "address"):
        if fields[key]:
            # 住所だけは末尾の番地を残す（短い英数字でノイズと同じ形のため）
            fields[key] = trim_ocr_noise(fields[key], keep_house_number=key == "address")

    if fields["address"]:
        fields["address"] = join_house_number(fields["address"])
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

    # 何も読めなかった名刺から氏名を作らない。
    #
    # 縦書きの名刺（実テスト 22枚目）は、どちらの読み取り機も意味のある文字を
    # 1つも取れない。それでも 姓『蟹』名『麗』が出ていた——1文字＋1文字の
    # 並びは氏名の形に見えるが、絵柄や罫線の読み崩れはいくらでもこの形になる。
    #
    # 見分けの手がかりは「ほかに何も取れていない」こと。メール・電話・
    # 郵便番号・会社名のどれか1つでも取れていれば、その名刺は読めている。
    # 何も無いのに1文字＋1文字だけが取れているなら、形が似ただけ。
    #
    # 空欄なら入力する人が気づく。誤った氏名は気づかれずに登録される。
    if len(fields["last_name"]) == 1 and len(fields["first_name"]) == 1:
        # ふりがなも「読めている」証拠に数える。`林 修`＋`はやし おさむ` は
        # 1文字＋1文字だが、読みが漢字より長く付いているので読み崩れではない。
        if not any(fields[key] for key in ("email", "tel", "mobile", "fax",
                                           "postal_code", "address", "company_name",
                                           "department_name", "title", "url",
                                           "last_name_kana", "first_name_kana")):
            fields["last_name"] = fields["first_name"] = ""
            confidence.pop("last_name", None)
            confidence.pop("first_name", None)

    leftovers =[line for index, line in enumerate(cleaned) if index not in used]
    fields["note"] = "\n".join(leftovers)
    return {"fields": fields, "confidence": confidence}
