# Windows 用の起動ファイル

コマンドを打たずに、ダブルクリックで操作するためのバッチファイルです。

## はじめに

`create-desktop-shortcuts.bat` をダブルクリックすると、デスクトップに
**「名刺システム」フォルダ**が作られ、次の6つのショートカットが入ります。
あとはこのフォルダから番号順に実行してください。

| ショートカット | 内容 | tesseract |
| --- | --- | --- |
| 1 セットアップ | Python の実行環境を作り、必要な部品を入れる | 不要 |
| 2 練習サンプルを作る | 練習用の名刺16枚・領収書12枚を生成 | 不要 |
| 3 ラベル入力（練習） | 入力画面を試す | 不要 |
| 4 名刺を仕分ける | スキャンフォルダから名刺だけを取り出す | **必要** |
| 5 ラベル入力（実際の名刺） | 実名刺に正解ラベルを付ける | 不要 |
| 6 アプリを起動 | 名刺管理システム本体を開く | **必要** |

**まず 1 → 2 → 3 を実行してください。** ここまでは tesseract が無くても動きます。
実際の名刺を扱う 4・6 では tesseract が必要です
（[インストーラ](https://github.com/UB-Mannheim/tesseract/wiki)。
導入時に **Japanese** と **Japanese (vertical)** を選ぶ）。

## 各ファイル

| ファイル | 対応するコマンド |
| --- | --- |
| `setup.bat` | `python -m venv .venv` ＋ `pip install -r requirements.txt` ＋ `pytest` |
| `make-practice-samples.bat` | `python -m poc.receipts --out .\poc\practice` |
| `label-practice.bat` | `python poc\label.py .\poc\practice` |
| `classify-scans.bat` | `python poc\classify.py <フォルダ> --copy-to .\poc\real-cards ...` |
| `label-real-cards.bat` | `python poc\label.py .\poc\real-cards` |
| `run-app.bat` | `python -m uvicorn bcards.main:app --app-dir src` |

いずれも `app` フォルダへ移動してから実行するため、置き場所を変えないでください
（ショートカット経由なら問題ありません）。

## うまくいかないとき

| 症状 | 対処 |
| --- | --- |
| 「Python が見つかりません」 | [Python](https://www.python.org/downloads/windows/) を入れ直す。**Add python.exe to PATH** にチェック |
| 「セットアップがまだです」 | 先に「1 セットアップ」を実行する |
| 「tesseract が見つかりません」 | 上記のインストーラを実行し、**画面を開き直す**（PATH の反映に必要） |
| 文字が化ける | 動作には支障ありません。気になる場合は PowerShell から直接実行してください（`app/README.md` の「0. Windows で動かす場合」参照） |
| 画面がすぐ閉じる | ショートカットではなく `.bat` を直接ダブルクリックした場合に起きます。ショートカットから実行してください |
| ブラウザが開かない | 黒い画面に出ている URL（`http://127.0.0.1:8100/` など）を手で開いてください |

黒い画面に出たエラーは、そのまま画面を撮って共有していただければ調べられます。
