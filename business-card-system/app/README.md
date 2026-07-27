# 名刺一元管理システム アプリケーション

要件定義書 [`../requirements-v0.2.md`](../requirements-v0.2.md) と設計ドキュメント
（[データモデル](../data-model-v0.3.md) / [画面・機能一覧](../screens-and-functions-v0.3.md)）を実装した Web アプリケーション。

- サーバーサイドレンダリングの Web アプリ（FastAPI + Jinja2）
- データベースは SQLite（本番は PostgreSQL 等へ切り替え可能）
- 画像はローカルのオブジェクトストレージ層に保存（S3 / Blob / GCS へ差し替え可能）
- OCR はプロバイダを差し替え可能。既定はローカルの tesseract（画像を外部へ送信しない）

---

## 1. 起動方法

```bash
cd business-card-system/app

# 依存をインストールして起動（初回は .venv を自動作成）
./run.sh

# 初期ユーザーの作成（別ターミナルで実行）
PYTHONPATH=src ./.venv/bin/python seed.py

# デモ用の名刺画像を生成し、取込〜OCR〜登録まで実行する場合
PYTHONPATH=src ./.venv/bin/python seed.py --demo --count 6
```

ブラウザで <http://127.0.0.1:8000/> を開く。

### seed.py が作成するアカウント

| ログインID | 権限 | パスワード |
| --- | --- | --- |
| admin | 管理者 | `AdminPass123!` |
| sato | 一般利用者 | `MemberPass123!` |
| suzuki | 一般利用者 | `MemberPass123!` |

> デモ用の初期パスワードです。実運用では必ず変更してください。

### OCR について

既定は `tesseract`（日本語 `jpn` + 英語 `eng`）。Ubuntu/Debian では次で導入する。

```bash
apt-get install -y tesseract-ocr tesseract-ocr-jpn
```

tesseract が無い環境では `BCARDS_OCR_PROVIDER=mock` を指定すると、擬似OCRで取込フローだけを確認できる。

---

## 2. テスト

```bash
cd business-card-system/app
./.venv/bin/python -m pytest tests -q
```

要件の主要項目（認証・IP制限・取込・OCR確認・6択登録・履歴・削除復元完全削除・共有範囲・CSV出力の監査記録・編集権限の切替）を
18 件のテストで検証している。テストは外部サービスに依存しない（OCRは mock プロバイダ）。

---

## 3. 設定（環境変数）

| 変数 | 既定値 | 内容 |
| --- | --- | --- |
| `BCARDS_DATABASE_URL` | `sqlite:///storage/bcards.db` | データベース接続文字列 |
| `BCARDS_STORAGE_DIR` | `storage/objects` | 画像の保存先 |
| `BCARDS_SECRET_KEY` | `dev-secret-key-change-me` | セッション署名鍵（**本番では必ず変更**） |
| `BCARDS_SECURE_COOKIE` | `0` | HTTPS 環境では `1` |
| `BCARDS_OCR_PROVIDER` | `tesseract` | `mock` / `tesseract` / `azure` |
| `BCARDS_OCR_LANGUAGES` | `jpn+eng` | tesseract の言語 |
| `BCARDS_AZURE_DI_ENDPOINT` / `BCARDS_AZURE_DI_KEY` | 空 | Azure OCR 利用時のみ |
| `BCARDS_ENFORCE_IP_RESTRICTION` | `1` | `0` でIP制限を無効化（開発用） |
| `BCARDS_STORAGE_QUOTA_BYTES` | 50GB | 容量アラートの分母 |
| `BCARDS_DISPLAY_MAX_EDGE` | `1600` | 表示用画像の長辺 |

運用中に変える値（無操作ログアウト時間、CSV大量出力の閾値、編集権限ポリシー等）は
**管理画面のシステム設定**から変更する（DBの `app_setting` に保存され、変更履歴に残る）。

---

## 4. 構成

```
app/
├── run.sh / seed.py / requirements.txt
├── src/bcards/
│   ├── main.py            アプリ本体・セッション/端末IDのミドルウェア・例外ハンドラ
│   ├── config.py          環境変数による設定
│   ├── db.py / models.py  DB接続とデータモデル（ER設計に対応）
│   ├── security.py        パスワード(PBKDF2)・TOTP・セッション署名・IP判定
│   ├── deps.py            認証・権限・IP制限・CSRF
│   ├── audit.py           監査ログ / 変更履歴の記録
│   ├── settings_store.py  管理画面から変更できるシステム設定
│   ├── routers/           auth / home / cards / imports / exports / admin
│   ├── services/
│   │   ├── images.py      形式変換・名刺検出・台形補正・回転・明るさ・品質警告・分割
│   │   ├── ocr/           プロバイダ（mock/tesseract/azure）と項目分離パーサ
│   │   ├── importer.py    取込パイプライン（状態遷移・表裏判定・再処理）
│   │   ├── dedupe.py      重複人物のスコアリング
│   │   ├── cards.py       登録6択・編集・論理削除・復元・完全削除・人物統合
│   │   ├── search.py      検索条件の組み立て
│   │   ├── csv_export.py  CSV生成と出力ログ
│   │   └── storage.py     オブジェクトストレージ層
│   ├── templates/         画面（Jinja2）
│   └── static/app.css
└── tests/
```

---

## 5. 要件との対応

| 要件 | 実装 |
| --- | --- |
| §1 利用者・状態（有効/利用停止/退職・管理者/一般） | `models.User`、管理画面 `/admin/users`。部署テーブルは定義のみ（任意） |
| §2 原本／表示用画像の分離、容量通知 | `services/images.make_variants`、ホーム・`/admin/storage` の容量アラート |
| §3 一括アップロードと5状態の進捗表示 | `/imports/upload`、`ImportItem.status`（取込待ち/OCR処理中/確認待ち/登録完了/エラー） |
| §4 形式対応・画像補正・PDF分割・複数名刺分割・表裏判定・品質警告 | `services/images.py`、`importer._detect_front_back` |
| §5 クラウド前提の構成 | ストレージ層とDB接続を差し替え可能に分離 |
| §6 IP制限・管理者の社外アクセス・MFA・自動ログアウト・ログイン履歴 | `deps.check_network_access`、`security.verify_totp`、`main.session_middleware`、`/admin/logins` |
| §7 全利用者による共有・編集権限・変更履歴 | 検索/閲覧に所有者制限なし、`card_edit_policy` 設定、`ChangeHistory`（変更者/日時/端末/IP/前後/理由） |
| §8 外部OCRの選択・自動確定しない | `services/ocr/`、確認画面 `/imports/items/{id}` を経ないと登録できない |
| §9 CSV出力と監査ログ | `services/csv_export.py`、`CsvExportLog`、大量出力の確認画面、CSVへの管理番号・注意表示 |
| §10 保存期限なし・退職者データ保持・1人物複数名刺・6択登録・論理削除と完全削除 | `services/cards.py`、`/persons/{id}` の時系列表示、`/admin/deleted` |

---

## 6. 実装上の判断と、本番導入前に必要な作業

### 判断（未確定論点への暫定対応）

未確定事項（[論点整理](../open-issues-v0.3.md)）については、**設定で切り替えられる形**にして推奨値を既定にしている。

- 編集権限（論点A）：既定は `all_users`（全利用者が編集可＋全変更を履歴保持）。統合・復元・完全削除は管理者限定
- OCR（論点C）：プロバイダ差し替え式。既定はローカル tesseract。項目分離はルールベース（方式1）で、LLM方式へ差し替え可能な戻り値の形にしている
- 名寄せ（論点D）：自動統合はせず、スコアと一致理由を提示して利用者が選択
- 画像補正（論点G）：外周検出・台形補正・回転・明るさ・影軽減・品質警告を実装

### 本番導入前に必要な作業

1. `BCARDS_SECRET_KEY` の変更と HTTPS 化（`BCARDS_SECURE_COOKIE=1`）
2. データベースを PostgreSQL 等へ変更し、マイグレーション管理（Alembic）を導入する
3. `services/storage.py` をクラウドのオブジェクトストレージ実装に差し替える
4. 取込処理を非同期ワーカー（キュー）へ移行する。現在はアップロードのリクエスト内で同期処理している
5. 認証基盤（Entra ID 等）に委譲する場合は `security.py` / `routers/auth.py` を置き換える
6. バックアップ（DB・オブジェクトストレージ）と復旧手順の整備
7. 監査ログのアーカイブ方針（保存期間は論点H）

### 現時点で未実装の項目

| 項目 | 理由 |
| --- | --- |
| 修正申請＋管理者承認の編集方式（論点Aの案3） | 採用が未決定のため。設定値のみ用意 |
| 会社の統合（人物統合は実装済み） | 優先度が低く、論点として未起票 |
| 部署・グループ画面 | 要件§1で初期リリース対象外 |
| CSVの非同期出力 | 閾値（論点I）の確定待ち |
| スキャナーの直接制御 | 要件§4で明示的に対象外 |
