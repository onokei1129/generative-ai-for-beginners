# 名刺一元管理システム アプリケーション

要件定義書 [`../requirements-v0.2.md`](../requirements-v0.2.md) と設計ドキュメント
（[データモデル](../data-model-v0.3.md) / [画面・機能一覧](../screens-and-functions-v0.3.md)）を実装した Web アプリケーション。

- サーバーサイドレンダリングの Web アプリ（FastAPI + Jinja2）
- データベースは SQLite（開発）／ PostgreSQL（本番）。スキーマは Alembic で管理する
- 画像はオブジェクトストレージ層に保存。ローカル／S3（MinIO 等の S3 互換を含む）を設定で切替
- OCR はプロバイダを差し替え可能。既定はローカルの tesseract（画像を外部へ送信しない）
- 取込はキュー方式。アップロードは即応答し、ワーカーが順次処理する

> 本番環境の構築・運用手順（HTTPS、鍵、バックアップ、復元訓練、監視）は
> [`../operations-guide.md`](../operations-guide.md) にまとめている。

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

既定は `tesseract`（日本語 `jpn` + 縦書き `jpn_vert` + 英語 `eng`）。Ubuntu/Debian では次で導入する。

```bash
apt-get install -y tesseract-ocr tesseract-ocr-jpn tesseract-ocr-jpn-vert
```

tesseract が無い環境では `BCARDS_OCR_PROVIDER=mock` を指定すると、擬似OCRで取込フローだけを確認できる。

項目分離（OCRテキストを氏名・会社名などに分ける処理）は2方式ある。

| 設定 | 方式 | 備考 |
| --- | --- | --- |
| `BCARDS_FIELD_EXTRACTOR=rule` | ルールベース（正規表現・辞書） | 追加費用なし。合成サンプルでの正答率 44.8% |
| `BCARDS_FIELD_EXTRACTOR=llm` | Claude API（画像＋OCRテキスト → 構造化出力） | `ANTHROPIC_API_KEY` が必要 |
| `BCARDS_FIELD_EXTRACTOR=auto`（既定） | 認証情報があればLLM、無ければルール | LLM側が失敗した場合もルールへ自動フォールバック |

精度の実測は [../ocr-poc-report.md](../ocr-poc-report.md) を参照。

### 取込ワーカー（キュー方式）

アップロードはファイルを保存してキュー（`import_file` テーブル）に積むだけで応答を返し、
実際の画像処理とOCRはワーカーが行う。既定ではアプリと同じプロセスでワーカースレッドが動く。

```bash
# 別プロセスでワーカーを動かす場合
BCARDS_WORKER_ENABLED=0 ./run.sh                 # Web側はワーカーを起動しない
PYTHONPATH=src ./.venv/bin/python worker.py      # ワーカー（Ctrl-Cで安全に停止）
```

- 同時実行数は `BCARDS_WORKER_CONCURRENCY`（既定2）
- ワーカーが落ちて処理中のまま残ったファイルは、`BCARDS_WORKER_LEASE_SECONDS`（既定600秒）経過後にキューへ戻る（最大3回まで再試行）
- 取込状況画面（`/imports`）でキューの滞留を確認できる

#### OCRの並列度に注意（`BCARDS_OCR_THREAD_LIMIT`）

tesseract は既定でCPU数ぶんのOpenMPスレッドを使う。ワーカーを複数動かすと
「ワーカー数 × CPU数」のスレッドが同時に走り、CPUの奪い合いで取込が進まなくなる。
アプリは既定で `OMP_THREAD_LIMIT=1` を子プロセスへ渡してこれを防いでいる。
4CPUのサーバーで同じ画像6件を同時にOCRさせた実測値は次のとおり。

| 条件 | 6件の処理時間 |
| --- | --- |
| スレッド数無制限 | 10分経っても完了せず（打ち切り） |
| `OMP_THREAD_LIMIT=1`（既定） | 2.1秒 |

OCRの精度には影響しない（PoCの正答率 44.8% は設定前後で同一）。

また、OCR実行中はDBトランザクションを閉じている。閉じないとPostgreSQL側に
`idle in transaction` の接続が滞留するため。処理の途中でワーカーが落ちた場合、
作りかけの取込明細は次の再処理時に自動で片付けられる（`ImportItem.import_file_id` で追跡）。

### OCR精度のPoC

`poc/` に、正解ラベル付きサンプルで精度を実測する仕組みがある。

```bash
PYTHONPATH=src ./.venv/bin/python -m poc.runner --out ../ocr-poc-report.md --json poc/last-result.json
PYTHONPATH=src ./.venv/bin/python -m poc.runner --real ./poc/samples --out ../real.md   # 実名刺で計測
PYTHONPATH=src ./.venv/bin/python -m poc.runner --only E --out /tmp/llm.md              # LLM抽出だけ計測
```

項目別正答率・1枚あたりの修正項目数・処理時間・（LLM利用時は）費用を出力する。

#### スキャンフォルダから名刺だけを取り出す

ScanSnap の保存先のように名刺と領収書が混在したフォルダから、名刺だけを仕分ける。
画像を外部へ送信せず、ローカルだけで完結する。

```bash
# 判定するだけ（ファイルは動かさない）
PYTHONPATH=src ./.venv/bin/python poc/classify.py "/path/to/ScanSnap" --report sort.md

# 名刺と判定したものを別フォルダへコピーする（不明も分けて入れる）
PYTHONPATH=src ./.venv/bin/python poc/classify.py "/path/to/ScanSnap" \
    --copy-to ./poc/real-cards --copy-unknown --csv sort.csv
```

判定は「形状（名刺は縦横比 約1.65）」と「文字（領収書系／名刺系の語）」のスコアを合算し、
**名刺 / 領収書 / 不明** に分ける。迷ったものは自動で振り分けず不明に落とす。

合成サンプル28件（名刺16・領収書12）での実測値：

| 条件 | 正答 | 不明（要目視） | 誤判定 |
| --- | --- | --- | --- |
| 形状＋文字（既定） | 28/28（100%） | 0 | 0 |
| 形状のみ（`--no-ocr`） | 16/28（57.1%） | 8 | 4 |
| 余白つき・傾きあり | 19/28（67.9%） | 9 | 0 |

自分の環境で数値を確かめる場合：

```bash
PYTHONPATH=src ./.venv/bin/python -m poc.receipts --out /tmp/mixed      # 混在フォルダを生成
PYTHONPATH=src ./.venv/bin/python -m poc.classify_eval /tmp/mixed       # 混同行列と正答率
```

実データで測る場合は、対象フォルダに `_truth.csv`（`file,truth` の2列。
`truth` は `business_card` / `receipt`）を用意すれば同じコマンドが使える。

---

## 2. テスト

```bash
cd business-card-system/app
./.venv/bin/python -m pytest tests -q
```

要件の主要項目（認証・IP制限・取込キュー・OCR確認・6択登録・履歴・削除復元完全削除・共有範囲・
CSV出力の監査記録・編集権限の切替・ストレージ実装の切替・起動時の設定チェック・取込の再処理）を
71 件のテストで検証している。テストは外部サービスに依存しない（OCRは mock プロバイダ、
LLM抽出は HTTP トランスポートを差し替えた契約テスト、S3 は moto で模擬）。

同じテストを PostgreSQL に対しても実行できる（本番と同じDBで検証するため）。

```bash
createdb bcards_test
BCARDS_DATABASE_URL="postgresql+psycopg://bcards:***@127.0.0.1:5432/bcards_test" \
  ./.venv/bin/python -m pytest tests -q
```

SQLite・PostgreSQL のいずれでも 71 件すべて通ることを確認している。

---

## 3. 設定（環境変数）

| 変数 | 既定値 | 内容 |
| --- | --- | --- |
| `BCARDS_ENV` | `development` | `production` で起動時チェックを厳格にする |
| `BCARDS_DATABASE_URL` | `sqlite:///storage/bcards.db` | データベース接続文字列 |
| `BCARDS_AUTO_CREATE_TABLES` | `1` | 起動時の自動テーブル作成。**本番は `0`**（Alembic で管理） |
| `BCARDS_DB_POOL_SIZE` / `BCARDS_DB_MAX_OVERFLOW` | `5` / `10` | PostgreSQL の接続プール |
| `BCARDS_STORAGE_BACKEND` | `local` | `local` / `s3` |
| `BCARDS_STORAGE_DIR` | `storage/objects` | `local` のときの保存先 |
| `BCARDS_S3_BUCKET` / `BCARDS_S3_KEY_PREFIX` | 空 / `business-cards` | `s3` のとき必須／バケット内の接頭辞 |
| `BCARDS_S3_REGION` / `BCARDS_S3_ENDPOINT_URL` | 空 | リージョン／MinIO 等の S3 互換ストレージ |
| `BCARDS_S3_SSE` | `AES256` | 保存時暗号化。空文字で無効 |
| `BCARDS_STORAGE_USAGE_CACHE_SECONDS` | `300` | 使用量の集計をキャッシュする秒数。`0` で毎回集計（後述） |
| `BCARDS_SECRET_KEY` | `dev-secret-key-change-me` | セッション署名鍵（**本番では必ず変更**） |
| `BCARDS_SECURE_COOKIE` | `0` | HTTPS 環境では `1` |
| `BCARDS_OCR_PROVIDER` | `tesseract` | `mock` / `tesseract` / `azure` |
| `BCARDS_OCR_LANGUAGES` | `jpn+jpn_vert+eng` | tesseract の言語 |
| `BCARDS_OCR_THREAD_LIMIT` | `1` | tesseract の OpenMP スレッド数。**変更非推奨**（上記参照） |
| `BCARDS_OCR_TIMEOUT_SECONDS` | `120` | 1回のOCRの上限秒数。超えたらそのファイルはエラー |
| `BCARDS_FIELD_EXTRACTOR` | `auto` | `rule` / `llm` / `auto` |
| `BCARDS_LLM_MODEL` | `claude-opus-5` | LLM抽出で使うモデル |
| `BCARDS_LLM_EFFORT` | `low` | LLM抽出のエフォート |
| `BCARDS_WORKER_ENABLED` | `1` | アプリ内でワーカーを起動する |
| `BCARDS_WORKER_CONCURRENCY` | `2` | ワーカースレッド数 |
| `BCARDS_WORKER_LEASE_SECONDS` | `600` | 処理中とみなす上限（超過でキューへ戻す） |
| `BCARDS_AZURE_DI_ENDPOINT` / `BCARDS_AZURE_DI_KEY` | 空 | Azure OCR 利用時のみ |
| `BCARDS_ENFORCE_IP_RESTRICTION` | `1` | `0` でIP制限を無効化（開発用） |
| `BCARDS_TRUSTED_PROXIES` | 空 | `X-Forwarded-For` を信用するプロキシのCIDR（カンマ区切り）。**未設定ならヘッダを信用せずTCP接続元を使う**（IP制限の詐称防止） |
| `BCARDS_STORAGE_QUOTA_BYTES` | 50GB | 容量アラートの分母 |
| `BCARDS_DISPLAY_MAX_EDGE` | `1600` | 表示用画像の長辺 |

運用中に変える値（無操作ログアウト時間、CSV大量出力の閾値、編集権限ポリシー等）は
**管理画面のシステム設定**から変更する（DBの `app_setting` に保存され、変更履歴に残る）。

`BCARDS_ENV=production` で起動すると設定を点検し、危険な設定（既定の秘密鍵、
HTTP のままの Cookie、IP制限の無効化など）があれば**起動を中止**する。
点検項目は [`../operations-guide.md` §4](../operations-guide.md#4-起動時の設定チェック) を参照。

### スキーマ管理（Alembic）

```bash
export BCARDS_DATABASE_URL="postgresql+psycopg://bcards:***@127.0.0.1:5432/bcards"
./.venv/bin/alembic upgrade head            # 適用
./.venv/bin/alembic current                 # 現在の版
./.venv/bin/alembic revision --autogenerate -m "変更内容"   # モデル変更後
```

自動生成された内容は必ず目視で確認し、`alembic downgrade -1 && alembic upgrade head` で
往復できることを確かめてから取り込む。

### 性能の測定

本番相当のデータ量を投入して、応答時間とバックアップ・復元の所要時間を測れる。
結果は [../capacity-report-2026-07.md](../capacity-report-2026-07.md) を参照。

```bash
# 架空データを1万件投入する（画像つきで約8分。BCARDS_ENV=production では実行を拒否する）
PYTHONPATH=src ./.venv/bin/python ops/loadgen.py --cards 10000
PYTHONPATH=src ./.venv/bin/python ops/loadgen.py --cards 10000 --no-images   # DBだけ・高速

# 応答時間を測る
PYTHONPATH=src ./.venv/bin/python ops/bench.py --out capacity.md
```

名刺1万件・画像3万件（1.1GB）での実測値：

| 項目 | 実測 | 目標 |
| --- | --- | --- |
| 検索応答時間 | 337 ms（最悪） | 1秒以内 |
| ホーム画面 | 41 ms | — |
| CSV全件出力（1万件） | 2.85 秒 | 10秒以内 |
| バックアップ取得 | 56 秒 | — |
| 復元＋整合性チェック | 41 秒 | RTO 2営業時間 |

> 使用量の集計（`storage.total_bytes()`）はローカルなら全走査、S3ならバケット全体の
> リストになるため、既定で300秒キャッシュしている（`BCARDS_STORAGE_USAGE_CACHE_SECONDS`）。
> キャッシュを無効にするとホーム画面が画像3万件で約0.5秒遅くなる。

---

## 4. 構成

```
app/
├── run.sh / seed.py / worker.py / requirements.txt
├── alembic.ini / migrations/  スキーマのマイグレーション
├── ops/                   運用スクリプト
│   ├── backup.sh          DB（pg_dump）と画像の取得・世代管理
│   ├── restore.sh         復元（チェックサム検証・件数確認つき）
│   ├── verify.py          DBの画像レコードに対する実体の有無を確認
│   ├── archive_logs.py    監査ログのアーカイブと期限切れの破棄（日次バッチ）
│   ├── loadgen.py         本番相当の架空データ投入（性能測定用。本番では実行不可）
│   └── bench.py           検索・一覧・容量集計の応答時間を測る
├── poc/                   OCR精度の計測
│   ├── samples.py         正解ラベル付きの名刺サンプル生成
│   ├── runner.py          パイプライン比較と精度レポート
│   ├── classify.py        名刺／領収書の仕分け（混在フォルダ対策）
│   ├── receipts.py        検証用の領収書サンプル生成
│   └── classify_eval.py   仕分けの正答率（混同行列）
├── src/bcards/
│   ├── main.py            アプリ本体・セッション/端末IDのミドルウェア・例外ハンドラ
│   ├── config.py          環境変数による設定
│   ├── db.py / models.py  DB接続とデータモデル（ER設計に対応）
│   ├── security.py        パスワード(PBKDF2)・TOTP・セッション署名・IP判定
│   ├── startup.py         起動時の設定チェック（本番で危険な設定なら起動中止）
│   ├── deps.py            認証・権限・IP制限・CSRF
│   ├── audit.py           監査ログ / 変更履歴の記録
│   ├── settings_store.py  管理画面から変更できるシステム設定
│   ├── routers/           auth / home / cards / imports / exports / admin
│   ├── services/
│   │   ├── images.py      形式変換・名刺検出・台形補正・回転・明るさ・品質警告・分割
│   │   ├── ocr/           プロバイダ（mock/tesseract/azure）と項目分離パーサ
│   │   ├── importer.py    取込パイプライン（状態遷移・表裏判定・再処理）
│   │   ├── queue.py       取込キュー（排他取得・滞留回収・ジョブ状態の導出）
│   │   ├── worker.py      ワーカー（アプリ内スレッド／別プロセス）
│   │   ├── dedupe.py      重複人物のスコアリング
│   │   ├── cards.py       登録6択・編集・論理削除・復元・完全削除・人物統合
│   │   ├── search.py      検索条件の組み立て
│   │   ├── csv_export.py  CSV生成と出力ログ
│   │   ├── log_archive.py 監査ログのアーカイブ・破棄（論点H）
│   │   └── storage.py     オブジェクトストレージ層（local / s3 を設定で切替）
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
| §3 一括アップロードと5状態の進捗表示、大量取込 | `/imports/upload` はキュー登録のみで即応答（実測0.03秒）。`services/queue.py` + `services/worker.py` が順次処理。`ImportItem.status`（取込待ち/OCR処理中/確認待ち/登録完了/エラー） |
| §4 形式対応・画像補正・PDF分割・複数名刺分割・表裏判定・品質警告 | `services/images.py`、`importer._detect_front_back` |
| §5 クラウド前提の構成 | ストレージ層とDB接続を差し替え可能に分離 |
| §6 IP制限・管理者の社外アクセス・MFA・自動ログアウト・ログイン履歴 | `deps.check_network_access`、`security.verify_totp`、`main.session_middleware`、`/admin/logins` |
| §7 全利用者による共有・編集権限・変更履歴 | 検索/閲覧に所有者制限なし、`card_edit_policy` 設定、`ChangeHistory`（変更者/日時/端末/IP/前後/理由） |
| §8 外部OCRの選択・自動確定しない | `services/ocr/`（mock/tesseract/azure ＋ ルール/LLM の項目分離）、確認画面 `/imports/items/{id}` を経ないと登録できない |
| §9 CSV出力と監査ログ | `services/csv_export.py`、`CsvExportLog`、大量出力の確認画面、CSVへの管理番号・注意表示 |
| §10 保存期限なし・退職者データ保持・1人物複数名刺・6択登録・論理削除と完全削除 | `services/cards.py`、`/persons/{id}` の時系列表示、`/admin/deleted` |

---

## 6. 実装上の判断と、本番導入前に必要な作業

### 判断（未確定論点への暫定対応）

未確定事項（[論点整理](../open-issues-v0.3.md)）については、**設定で切り替えられる形**にして推奨値を既定にしている。

- 編集権限（論点A）：既定は `all_users`（全利用者が編集可＋全変更を履歴保持）。統合・復元・完全削除は管理者限定
- OCR（論点C）：プロバイダ差し替え式。既定はローカル tesseract。項目分離はルール／LLMを設定で切替。**第1回PoCを実施し、結果を [../ocr-poc-report.md](../ocr-poc-report.md) にまとめた**
- 名寄せ（論点D）：自動統合はせず、スコアと一致理由を提示して利用者が選択
- 画像補正（論点G）：外周検出・台形補正・回転・明るさ・影軽減・品質警告を実装

### 本番導入準備の状況

| 項目 | 状況 | 内容 |
| --- | --- | --- |
| PostgreSQL 対応 | 実施済み | 接続プール・`ilike`・`SKIP LOCKED` を含め、全71テストを PostgreSQL 16 で確認 |
| マイグレーション管理 | 実施済み | Alembic を導入。`upgrade` / `downgrade` の往復を確認済み |
| オブジェクトストレージ | 実施済み | `local` / `s3`（S3互換含む）を設定で切替。S3 は moto でテスト |
| HTTPS・鍵・プロキシ | 手順を整備 | [運用手引き §2.4–2.5](../operations-guide.md#24-秘密鍵の生成) に nginx 設定例と `BCARDS_TRUSTED_PROXIES` の指定を記載 |
| 起動時の設定チェック | 実施済み | `BCARDS_ENV=production` で危険な設定を検出し起動を中止 |
| 取込の並列度・性能 | 実施済み | OCRのCPU競合を解消（10分超→2.1秒）。DBトランザクションもOCR中は閉じる |
| バックアップ・復元 | 実施済み | `ops/backup.sh` / `ops/restore.sh` / `ops/verify.py`。実機で取得→復元→検証まで確認 |
| 復元訓練 | 第1回実施済み | [実施記録](../restore-drill-2026-07.md)。手順の不具合を1件検出し修正、回帰テストを追加 |
| 性能・容量の実測 | 実施済み | 名刺1万件で[実測](../capacity-report-2026-07.md)。性能問題を2件検出し修正（ホーム画面 551→41ms、CSV出力 12.0→2.9秒） |
| 監査ログのアーカイブ | 実施済み | 論点Hを実装。1年でアーカイブ・3年で破棄（設定で変更可）。`ops/archive_logs.py` |
| ワーカーの分離 | 選択可能 | `worker.py` で別プロセス化できる。既定はアプリ内スレッド |

### 本番導入前に残っている作業

1. 認証基盤（Entra ID 等）に委譲する場合は `security.py` / `routers/auth.py` を置き換える
2. クラウド事業者・OCRサービスの確定（論点C）と、実名刺での精度実測
   （仕分けは `poc/classify.py` で行える。計測には正解ラベルの作成が必要）
3. 監査ログの保存期間（1年アーカイブ／3年破棄）の妥当性を社内規程と突き合わせる
4. 非機能要件の確定値（検索1秒以内・RTO 2営業時間）の決裁

### 現時点で未実装の項目

| 項目 | 理由 |
| --- | --- |
| 修正申請＋管理者承認の編集方式（論点Aの案3） | 採用が未決定のため。設定値のみ用意 |
| 会社の統合（人物統合は実装済み） | 優先度が低く、論点として未起票 |
| 部署・グループ画面 | 要件§1で初期リリース対象外 |
| CSVの非同期出力 | 閾値（論点I）の確定待ち |
| クラウドOCR・LLM抽出の精度実測 | 認証情報が未手配。計測基盤（`poc/`）とアダプタは実装済み |
| スキャナーの直接制御 | 要件§4で明示的に対象外 |
