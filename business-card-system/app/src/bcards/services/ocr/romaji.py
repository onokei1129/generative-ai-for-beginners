"""名刺に刷られたローマ字を、ふりがな（ひらがな）に直す。

## なぜ要るのか

日本の名刺は、氏名のすぐ下に**ふりがなではなくローマ字**を刷ることが多い。

    木村 央志
    Nakaji Kimura          ← ふりがなの位置にローマ字

これまでふりがなは「ひらがなだけの行」からしか取っておらず、この形の名刺は
ふりがなが空欄のままだった。実テスト（223枚）ではこの形が多く、そのぶんが
すべて手入力になっていた。

## 直せない部分がある——長音

名刺のローマ字はパスポート式ヘボンで刷られる。ここでは**長音が落ちる**。

    佐藤  さとう  →  Sato
    伊藤  いとう  →  Ito
    裕子  ゆうこ  →  Yuko

落ちた長音は字面からは戻せない。「語尾の o は必ず おう」という規則にも
できない——`Nakao`（なかお）・`Matsuo`（まつお）・`Ono`（おの）が壊れる。
`Ono`（おの）と `Kano`（かのう）は字面が同じ形で、区別する手がかりが無い。

素朴な変換の実測（実在の姓50・名20）:

    姓    39/50 = 78%
    名    11/20 = 55%
    合計  50/70 = 71%

**推測で長音を足さない。** 落ちたものは落ちたまま短く出す。名刺が長音を
書いているとき（`ō` `ô` `Itoh` `Ohno` `ou` `oo`）だけ長音にする。

外れ方には偏りがある。外れるのは 佐藤・伊藤・太郎 のような、**漢字を見れば
読みが分かる**名前。当たるのは 央志＝なかじ のような、**ローマ字が唯一の
手がかり**である珍しい読み。画面では未確認（黄色）で出るので、気づける側に
誤りが寄り、気づけない側に価値が寄る。

## 日本語のローマ字でないものは断る

`to_hiragana` は、変換しきれない字が1つでもあれば None を返す。日本語の
ローマ字は（子音＋）母音の並びに限られるので、そうでない綴りはここで落ちる。

    Patricio  → `tr` が作れない        → None
    Jeong     → `je` のあと `ng`       → None
    Vasquez   → `v` `q` が作れない     → None

ただし `Mike`（みけ）`Kate`（かて）のように、偶然この並びになる英語名は
通る。**呼び出す側で、同じ名刺に漢字かなの氏名があることを確かめること。**
"""

from __future__ import annotations

import re

# 3文字・2文字の綴りを先に見る（`sha` を `sa`+`ha` にしないため）。
#
# ヘボン式だけを入れる。訓令式（`si` `ti` `tu` `zi`）は入れない——名刺と
# パスポートはヘボンで刷るので要らないうえ、入れると `Tim` `Diana` のような
# 英語名まで変換できてしまい、断るはずのものが通る。
_SYLLABLES: tuple[tuple[str, str], ...] = (
    ("kya", "きゃ"), ("kyu", "きゅ"), ("kyo", "きょ"),
    ("gya", "ぎゃ"), ("gyu", "ぎゅ"), ("gyo", "ぎょ"),
    ("sha", "しゃ"), ("shu", "しゅ"), ("sho", "しょ"),
    ("cha", "ちゃ"), ("chu", "ちゅ"), ("cho", "ちょ"),
    ("nya", "にゃ"), ("nyu", "にゅ"), ("nyo", "にょ"),
    ("hya", "ひゃ"), ("hyu", "ひゅ"), ("hyo", "ひょ"),
    ("mya", "みゃ"), ("myu", "みゅ"), ("myo", "みょ"),
    ("rya", "りゃ"), ("ryu", "りゅ"), ("ryo", "りょ"),
    ("bya", "びゃ"), ("byu", "びゅ"), ("byo", "びょ"),
    ("pya", "ぴゃ"), ("pyu", "ぴゅ"), ("pyo", "ぴょ"),
    ("ja", "じゃ"), ("ju", "じゅ"), ("jo", "じょ"),
    ("shi", "し"), ("chi", "ち"), ("tsu", "つ"),
    ("ka", "か"), ("ki", "き"), ("ku", "く"), ("ke", "け"), ("ko", "こ"),
    ("sa", "さ"), ("su", "す"), ("se", "せ"), ("so", "そ"),
    ("ta", "た"), ("te", "て"), ("to", "と"),
    ("na", "な"), ("ni", "に"), ("nu", "ぬ"), ("ne", "ね"), ("no", "の"),
    ("ha", "は"), ("hi", "ひ"), ("fu", "ふ"), ("hu", "ふ"), ("he", "へ"), ("ho", "ほ"),
    ("ma", "ま"), ("mi", "み"), ("mu", "む"), ("me", "め"), ("mo", "も"),
    ("ya", "や"), ("yu", "ゆ"), ("yo", "よ"),
    ("ra", "ら"), ("ri", "り"), ("ru", "る"), ("re", "れ"), ("ro", "ろ"),
    ("wa", "わ"),
    ("ga", "が"), ("gi", "ぎ"), ("gu", "ぐ"), ("ge", "げ"), ("go", "ご"),
    ("za", "ざ"), ("ji", "じ"), ("zu", "ず"), ("ze", "ぜ"), ("zo", "ぞ"),
    ("da", "だ"), ("de", "で"), ("do", "ど"),
    ("ba", "ば"), ("bi", "び"), ("bu", "ぶ"), ("be", "べ"), ("bo", "ぼ"),
    ("pa", "ぱ"), ("pi", "ぴ"), ("pu", "ぷ"), ("pe", "ぺ"), ("po", "ぽ"),
    ("a", "あ"), ("i", "い"), ("u", "う"), ("e", "え"), ("o", "お"),
)

# 名刺が長音を書いてくれている印。
#
# `ō` は「おう」と「おお」の両方になる。名前では圧倒的に「おう」が多いので
# （佐藤・加藤・伊藤・太郎・一郎・洋子）そちらを既定にし、**語頭だけ「おお」**
# にする（大野・大塚・大久保。語頭の長い「オー」はほぼ「大」）。`Oh` の
# 扱いと同じ考え方。
_MACRONS = str.maketrans({
    "ā": "aa", "â": "aa", "ī": "ii", "î": "ii", "ū": "uu", "û": "uu",
    "ē": "ee", "ê": "ee", "ō": "ou", "ô": "ou",
})
_LONG_O_AT_HEAD = re.compile(r"^[ōô]")

# 促音になれる子音。`Hattori` の `tt`、`Sapporo` の `pp`、`Issei` の `ss`。
#
# **`m` `h` と母音は入れないこと。** `Gumma`（ぐんま）は促音ではなく撥音、
# `Ohhashi`（おおはし）は長音、`Ishii`（いしい）は母音の重なり。
_CAN_DOUBLE = frozenset("kstpc")

# 撥音の判定に使う。空文字（語末）を含めないよう、集合で持つ。
_VOWELS_AND_Y = frozenset("aiueoy")
_BEFORE_M_IS_N = frozenset("bmp")

# `Oh` で書かれた長音。子音か語末が続くときだけ長音とみなす。
#
#     Ohno   → oono  → おおの   語頭の `Oh` は「大」がほとんど（大野・大谷・大塚）
#     Kohno  → kouno → こうの   語中は「おう」
#     Itoh   → itou  → いとう
#     Kohei  → そのまま → こへい  母音が続くので `h` は「へ」の h。伸ばさない
_OH_AT_HEAD = re.compile(r"^oh(?![aiueoy])")
_OH_INSIDE = re.compile(r"oh(?![aiueoy])")


def to_hiragana(word: str) -> str | None:
    """ローマ字1語をひらがなに直す。直しきれなければ None。

    **推測しない。** 作れない綴りが1つでもあれば、部分的な結果を返さずに
    None を返す。中途半端なかなを欄に入れると、読める字と読めない字が
    混ざったものが「未確認」として保存される。
    """
    if not word:
        return None

    text = word.strip().lower()
    text = _LONG_O_AT_HEAD.sub("oo", text, count=1)
    text = text.translate(_MACRONS)
    # 撥音の区切り。`Jun'ichi` は じゅんいち で、じゅにち ではない。
    # **記号を落とすだけにしないこと**——落とすと `n` が「な行」に化ける。
    text = re.sub(r"n['’`]", "ン", text)
    text = _OH_AT_HEAD.sub("oo", text)
    text = _OH_INSIDE.sub("ou", text)
    if not text or not re.fullmatch(r"[a-zン]+", text):
        return None

    out: list[str] = []
    at = 0
    while at < len(text):
        here = text[at]

        if here == "ン":  # `n'` から来た撥音
            out.append("ん")
            at += 1
            continue

        # 促音。同じ子音が2つ続く。
        if at + 1 < len(text) and here == text[at + 1] and here in _CAN_DOUBLE:
            out.append("っ")
            at += 1
            continue

        # 撥音。母音と `y` の前以外の `n` は「ん」。b・m・p の前を `m` で
        # 綴る古い書き方（`Namba` `Shimbashi` `Gumma`）も「ん」にする。
        #
        # 続く字は**集合で見ること**。`following not in "aiueoy"` と書くと、
        # 語末（空文字）が「母音が続く」と判定される（Python では空文字は
        # どんな文字列にも含まれる）。`Ken` の `n` が「ん」にならず、行ごと
        # 断られていた。
        following = text[at + 1] if at + 1 < len(text) else ""
        if here == "n" and following not in _VOWELS_AND_Y:
            out.append("ん")
            at += 1
            continue
        if here == "m" and following in _BEFORE_M_IS_N:
            out.append("ん")
            at += 1
            continue

        for spell, kana in _SYLLABLES:
            if text.startswith(spell, at):
                out.append(kana)
                at += len(spell)
                break
        else:
            # 日本語のローマ字では作れない綴り。推測せずに断る。
            return None

    return "".join(out)


def name_to_hiragana(text: str) -> str | None:
    """空白で区切られたローマ字の氏名を、続けたひらがなにする。

    `Nakaji Kimura` のような1つの欄ぶんを想定する。どれか1語でも直せな
    ければ全体を None にする（片方だけ入れると、姓と名がずれる）。
    """
    words = [w for w in re.split(r"[\s　]+", (text or "").strip()) if w]
    if not words:
        return None
    kana = [to_hiragana(word) for word in words]
    if any(part is None for part in kana):
        return None
    return "".join(part for part in kana if part)
