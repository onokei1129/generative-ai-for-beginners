# 名刺一元管理システム ドキュメント

社内の名刺を一元管理するシステムの要件・設計ドキュメント。

## ドキュメント一覧

| ドキュメント | 内容 | バージョン | 状態 |
| --- | --- | --- | --- |
| [requirements-v0.2.md](./requirements-v0.2.md) | 要件定義書（最優先事項の確定内容） | Ver.0.2 | 確定 |
| [data-model-v0.3.md](./data-model-v0.3.md) | データモデル（人物／会社／名刺／変更履歴／監査ログのER設計） | Ver.0.3 | ドラフト |
| [open-issues-v0.3.md](./open-issues-v0.3.md) | 未確定事項の論点整理（編集権限・クラウド事業者・OCRサービス等） | Ver.0.3 | ドラフト（決裁待ち） |
| [screens-and-functions-v0.3.md](./screens-and-functions-v0.3.md) | 画面一覧・機能一覧 | Ver.0.3 | ドラフト |
| [ocr-poc-report.md](./ocr-poc-report.md) | OCR精度PoCの計測報告（論点C） | 第1回 | 実測済み |
| [app/](./app/) | 実装（動作するWebアプリケーション） | — | 動作確認済み |

## 読む順序

1. **requirements-v0.2.md** — 何を作るかの前提（確定済み）
2. **open-issues-v0.3.md** — 決めないと先に進めない事項。まずここを決裁する
3. **data-model-v0.3.md** — データ構造。論点A・C・D の決定を反映して確定する
4. **screens-and-functions-v0.3.md** — 画面・機能への展開。見積の入力とする
5. **ocr-poc-report.md** — OCR精度の実測結果。論点Cの判断材料
6. **app/README.md** — 実装の起動方法・構成・要件との対応

## アプリケーション

`app/` に、要件を満たす動作するアプリケーションを実装している。

```bash
cd app
./run.sh                                          # 起動（http://127.0.0.1:8000/）
PYTHONPATH=src ./.venv/bin/python seed.py --demo   # 初期ユーザーとデモ名刺を投入
./.venv/bin/python -m pytest tests -q              # テスト
```

技術構成：FastAPI + Jinja2 + SQLAlchemy(SQLite) + OpenCV/Pillow（画像補正）+ tesseract（OCR、差し替え可能）。
詳細は [app/README.md](./app/README.md) を参照。

## 現在のステータス

Ver.0.2 の確定事項をもとに、Ver.0.3 へ向けた設計ドラフトと実装を作成した段階。
[未確定事項の論点整理](./open-issues-v0.3.md#論点サマリ)の A〜P が決まり次第、各ドキュメントを Ver.0.3 として確定する。
未確定の論点は、アプリ側では管理画面のシステム設定で切り替えられるようにしてある。
