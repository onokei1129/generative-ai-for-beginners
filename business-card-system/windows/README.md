# Windows 用の起動ファイル

コマンドを打たずに、ダブルクリックで操作するためのバッチファイルです。

## はじめに

`create-desktop-shortcuts.bat` をダブルクリックすると、デスクトップに
**「名刺システム」フォルダ**が作られ、次の9つのショートカットが入ります。
あとはこのフォルダから番号順に実行してください。

| ショートカット | 内容 | tesseract |
| --- | --- | --- |
| 0 最新版に更新する | `git pull` して、ショートカットを作り直す | 不要 |
| 1 セットアップ | Python の実行環境を作り、必要な部品を入れる | 不要 |
| 2 練習サンプルを作る | 練習用の名刺16枚・領収書12枚を生成 | 不要 |
| 3 ラベル入力（練習） | 入力画面を試す（サンプルが無ければ自動で作ります） | 不要 |
| 4 名刺を仕分ける | スキャンフォルダから名刺だけを取り出す | **必要** |
| 5 仕分け結果を確認する | 名刺フォルダ・「不明」フォルダ・一覧を開く | 不要 |
| 6 ラベル入力（実際の名刺） | 実名刺に正解ラベルを付ける | 不要 |
| 7 進み具合を見る | あと何枚か・未確認の欄が残っていないかを表示 | 不要 |
| 8 精度を測る | OCRの正答率を測って `real-rule.md` に出す | **必要** |
| 9 アプリを起動 | 名刺管理システム本体を開く | **必要** |

**まず 1 → 2 → 3 を実行してください。** ここまでは tesseract が無くても動きます。
実際の名刺を扱う 4・8・9 では tesseract が必要です
（[インストーラ](https://github.com/UB-Mannheim/tesseract/wiki)。
導入時に **Japanese** と **Japanese (vertical)** を選ぶ）。

> **番号を付け直したため、以前に作ったショートカットとは番号がずれています。**
> `create-desktop-shortcuts.bat` をもう一度実行すると、古いショートカットを消して
> 作り直します（消えるのはショートカットだけで、名刺の画像やラベルには触れません）。

## 更新のしかた

**2回目以降は「0 最新版に更新する」を押すだけです。** `git pull` とショートカットの
作り直しをまとめて行います。

はじめて更新するとき（まだ「0」のショートカットが無いとき）だけ、手で取得します。

1. デスクトップ「名刺システム」の**どれかのショートカットを右クリック →
   「ファイルの場所を開く」**（`windows` フォルダが開きます）
2. エクスプローラの**アドレス欄**にパスを消して `cmd` と入力し Enter
3. 開いた画面で次の2行を実行

   ```
   cd ..\..
   git pull
   ```

4. `windows` フォルダの `create-desktop-shortcuts.bat` をダブルクリック

## 実名刺のテストの進め方

1回で終わらせる必要はありません。**6 と 7 を往復**しながら進めてください。

```
4 名刺を仕分ける
      ↓
5 仕分け結果を確認する ── 「不明」に入った画像を目視で振り分ける
      ↓
6 ラベル入力 ←──────┐   黄色い欄（未確認）を画像と見比べて直す
      ↓              │
7 進み具合を見る ─────┘   残りがあればまた 6 へ
      ↓
8 精度を測る
```

**「7 進み具合を見る」は次にやることを1行で出します。** 迷ったらこれを実行してください。
「8 精度を測る」も、測る前に同じ確認を自動で行います。

目安は**30枚以上**。それ未満でも測れますが、数字が安定しません。

## 各ファイル

| ファイル | 対応するコマンド |
| --- | --- |
| `update.bat` | `git pull` ＋ `create-desktop-shortcuts.bat`。実行中に自分自身が書き換わらないよう、一時フォルダへコピーしてから動く |
| `setup.bat` | `python -m venv .venv` ＋ `pip install -r requirements.txt` ＋ `pytest` |
| `make-practice-samples.bat` | `python -m poc.receipts --out .\poc\practice` |
| `label-practice.bat` | `python poc\label.py .\poc\practice` |
| `classify-scans.bat` | `python poc\classify.py <フォルダ> --copy-to .\poc\real-cards ...` |
| `label-real-cards.bat` | `python poc\label.py .\poc\real-cards` |
| `open-card-folder.bat` | エクスプローラで名刺フォルダ・`unknown`・`sort.md` を開くだけ |
| `check-progress.bat` | `python -m poc.progress .\poc\real-cards` |
| `measure-accuracy.bat` | `python poc\runner.py --real .\poc\real-cards --out real-rule.md` |
| `run-app.bat` | `python -m uvicorn bcards.main:app --app-dir src` |

いずれも `app` フォルダへ移動してから実行するため、置き場所を変えないでください
（ショートカット経由なら問題ありません）。

## うまくいかないとき

| 症状 | 対処 |
| --- | --- |
| 「Python が見つかりません」 | [Python](https://www.python.org/downloads/windows/) を入れ直す。**Add python.exe to PATH** にチェック |
| 「セットアップがまだです」 | 先に「1 セットアップ」を実行する |
| 「tesseract が見つかりません」 | 上記のインストーラを実行し、**画面を開き直す**（PATH の反映に必要） |
| 文字が化ける／`is not recognized as an internal or external command` | バッチが UTF-8 で保存されています。CP932 で保存し直してください（下記「文字コードについて」） |
| 画面がすぐ閉じる | ショートカットではなく `.bat` を直接ダブルクリックした場合に起きます。ショートカットから実行してください |
| ブラウザが開かない | 黒い画面に出ている URL（`http://127.0.0.1:8100/` など）を手で開いてください |
| 「名刺のフォルダがありません」 | 先に「4 名刺を仕分ける」を実行する |
| 精度が思ったより良い | 未確認の欄が残っている可能性があります。「7 進み具合を見る」で確認してください |
| 更新で「git が見つかりません」 | [Git for Windows](https://git-scm.com/download/win) を入れ、画面を開き直す |
| 更新できない（`local changes` 等） | 黒い画面で `git stash` を実行してから、もう一度「0」を押す。名刺の画像とラベルは git の管理外なので消えません |

黒い画面に出たエラーは、そのまま画面を撮って共有していただければ調べられます。

## 文字コードについて（編集する場合の注意）

バッチファイルは **CP932（Shift-JIS）＋ CRLF** で保存しています。

UTF-8 で保存すると、cmd.exe が日本語の途中で行を切ってしまい、
残りをコマンドとして解釈してエラーになります（`chcp 65001` を付けても起きます）。

```
[エラー] 練習用サンプルがありません。
'?」 を実行してください。' is not recognized as an internal or external command
```

編集するときは CP932 で保存できるエディタを使ってください。
リポジトリ側では `.gitattributes` で `*.bat -text` を指定し、
git がバイト列を変換しないようにしています（そのため diff は文字化けして見えます）。
