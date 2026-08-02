# 名刺一元管理システム ドキュメント

社内の名刺を一元管理するシステムの要件・設計ドキュメント。

## ドキュメント一覧

| ドキュメント | 内容 | バージョン | 状態 |
| --- | --- | --- | --- |
| [requirements-v0.2.md](./requirements-v0.2.md) | 要件定義書（最優先事項の確定内容） | Ver.0.2 | 確定 |
| [data-model-v0.3.md](./data-model-v0.3.md) | データモデル（人物／会社／名刺／変更履歴／監査ログのER設計） | Ver.0.3 | ドラフト |
| [open-issues-v0.3.md](./open-issues-v0.3.md) | 未確定事項の論点整理（編集権限・クラウド事業者・OCRサービス等） | Ver.0.3 | ドラフト（決裁待ち） |
| [screens-and-functions-v0.3.md](./screens-and-functions-v0.3.md) | 画面一覧・機能一覧 | Ver.0.3 | ドラフト |
| [personal-data-handling-v0.3.md](./personal-data-handling-v0.3.md) | 個人情報の取扱い（利用目的・安全管理措置・開示請求対応／論点M） | Ver.0.3 | **草案（法務／総務レビュー待ち）** |
| [ocr-poc-report.md](./ocr-poc-report.md) | OCR精度PoCの計測報告（論点C） | 第1回 | 実測済み |
| [ocr-decision-2026-08.md](./ocr-decision-2026-08.md) | 論点Cの決裁報告（最新の実測・費用・推奨。§6に案2の実施結果） | 2026-08 | 案2 実施済み／**残り決裁待ち** |
| [operations-guide.md](./operations-guide.md) | 本番導入・運用手引き（構築／HTTPS／バックアップ／監査ログのアーカイブ／監視） | Ver.0.3 | ドラフト |
| [restore-drill-2026-07.md](./restore-drill-2026-07.md) | 復元訓練 第1回の実施記録 | 第1回 | 実施済み |
| [capacity-report-2026-07.md](./capacity-report-2026-07.md) | 本番相当データでの性能実測（検索応答時間・RTO） | 第1回 | 実測済み |
| [app/](./app/) | 実装（動作するWebアプリケーション） | — | 動作確認済み |
| [windows/](./windows/) | Windows用の起動ファイル（ダブルクリックで操作） | — | — |

## 読む順序

1. **requirements-v0.2.md** — 何を作るかの前提（確定済み）
2. **open-issues-v0.3.md** — 決めないと先に進めない事項。まずここを決裁する
3. **data-model-v0.3.md** — データ構造。論点A・C・D の決定を反映して確定する
4. **screens-and-functions-v0.3.md** — 画面・機能への展開。見積の入力とする
5. **personal-data-handling-v0.3.md** — 個人情報の取扱い。5章が法務／総務への確認事項の一覧
6. **ocr-poc-report.md** — OCR精度の実測結果。論点Cの判断材料
   （最新の数値と推奨は **ocr-decision-2026-08.md**）
7. **app/README.md** — 実装の起動方法・構成・要件との対応
8. **operations-guide.md** — 本番環境の構築と運用（システム管理者向け）

## アプリケーション

`app/` に、要件を満たす動作するアプリケーションを実装している。

```bash
cd app
./run.sh                                          # 起動（http://127.0.0.1:8000/）
./.venv/bin/python seed.py --demo   # 初期ユーザーとデモ名刺を投入
./.venv/bin/python -m pytest tests -q              # テスト
```

技術構成：FastAPI + Jinja2 + SQLAlchemy（SQLite／PostgreSQL）+ Alembic + OpenCV/Pillow（画像補正）
+ tesseract（OCR、差し替え可能）。画像の保存先はローカル／S3 を設定で切替。
詳細は [app/README.md](./app/README.md) を参照。

本番環境へ入れる場合の手順は [operations-guide.md](./operations-guide.md) にまとめている。

## 現在のステータス

Ver.0.2 の確定事項をもとに、Ver.0.3 へ向けた設計ドラフトと実装を作成し、
本番導入準備（PostgreSQL 対応・マイグレーション管理・オブジェクトストレージ切替・
起動時の設定チェック・バックアップと復元手順・取込性能の是正）まで完了した段階。

[未確定事項の論点整理](./open-issues-v0.3.md#論点サマリ)の A〜P が決まり次第、各ドキュメントを Ver.0.3 として確定する。
未確定の論点は、アプリ側では管理画面のシステム設定で切り替えられるようにしてある。
