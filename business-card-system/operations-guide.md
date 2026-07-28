# 名刺一元管理システム 本番導入・運用手引き Ver.0.3

要件 Ver.0.2 の §5（サーバー構成）・§6（アクセス範囲）・§9（監査ログ）・§10（保存期間）を
実際に運用する手順に落としたものです。開発環境の起動方法は `app/README.md` を参照してください。

- 対象読者: システム管理者
- 前提: PostgreSQL 16 以上、Python 3.11 以上、リバースプロキシ（HTTPS 終端）

---

## 目次

1. [構成](#1-構成)
2. [初期構築](#2-初期構築)
3. [環境変数](#3-環境変数)
4. [起動時の設定チェック](#4-起動時の設定チェック)
5. [取込ワーカーの台数とOCRの並列度](#5-取込ワーカーの台数とocrの並列度)
6. [バックアップ](#6-バックアップ)
7. [復元と復元訓練](#7-復元と復元訓練)
8. [スキーマ変更（マイグレーション）](#8-スキーマ変更マイグレーション)
9. [監視項目](#9-監視項目)
10. [障害時の対応](#10-障害時の対応)

---

## 1. 構成

```
          [社内ネットワーク / VPN]
                    │  HTTPS
          ┌─────────▼──────────┐
          │ リバースプロキシ    │  TLS終端・X-Forwarded-For 付与
          └─────────┬──────────┘
                    │
     ┌──────────────▼──────────────┐
     │ アプリケーション（uvicorn）  │  Webリクエスト処理
     └───┬───────────────────┬─────┘
         │                   │
   ┌─────▼──────┐   ┌────────▼─────────┐
   │ PostgreSQL │   │ オブジェクトストレージ │
   │            │   │ （S3 / MinIO / ローカル）│
   └─────┬──────┘   └────────┬─────────┘
         │                   │
     ┌───▼───────────────────▼───┐
     │ 取込ワーカー（worker.py）  │  画像処理・OCR
     └───────────────────────────┘
```

取込はキュー方式です。アップロードはファイルを保存してキューに積むだけで即座に応答し
（実測 3ファイルで 0.05 秒）、画像処理と OCR はワーカーが順次実行します。

ワーカーの動かし方は 2 通りあります。

| 方式 | 設定 | 向いている場面 |
| --- | --- | --- |
| アプリ内スレッド（既定） | `BCARDS_WORKER_ENABLED=1` | 10名規模・単一サーバー |
| 別プロセス | アプリ側 `BCARDS_WORKER_ENABLED=0` にして `python worker.py` | 取込が多い・OCRでWebを詰まらせたくない |

---

## 2. 初期構築

### 2.1 データベース

```bash
sudo -u postgres createuser bcards --pwprompt
sudo -u postgres createdb bcards --owner bcards
```

### 2.2 アプリケーション

```bash
cd app
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 日本語OCR（tesseract を使う場合）
sudo apt-get install -y tesseract-ocr tesseract-ocr-jpn tesseract-ocr-jpn-vert
```

### 2.3 スキーマ作成

本番では起動時の自動テーブル作成を使わず、Alembic で管理します。

```bash
export BCARDS_DATABASE_URL="postgresql+psycopg://bcards:***@db:5432/bcards"
.venv/bin/alembic upgrade head
```

### 2.4 秘密鍵の生成

セッション Cookie の署名に使います。使い回さず、環境ごとに生成してください。

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

### 2.5 HTTPS とリバースプロキシ

アプリは HTTP で待ち受け、TLS はリバースプロキシで終端します。
プロキシを挟む場合は、接続元 IP を正しく記録するために **必ず** `BCARDS_TRUSTED_PROXIES` を
設定してください（要件§9 の操作ログ、§6 の IP 制限がこの値に依存します）。

nginx の例:

```nginx
server {
    listen 443 ssl http2;
    server_name bcards.example.co.jp;

    ssl_certificate     /etc/ssl/certs/bcards.crt;
    ssl_certificate_key /etc/ssl/private/bcards.key;
    ssl_protocols       TLSv1.2 TLSv1.3;

    client_max_body_size 64m;   # 名刺画像の一括アップロード用

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host              $host;
        proxy_set_header X-Real-IP         $remote_addr;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

対応するアプリ側の設定:

```bash
export BCARDS_SECURE_COOKIE=1
export BCARDS_TRUSTED_PROXIES="127.0.0.1/32"   # プロキシ自身のアドレス
```

`BCARDS_TRUSTED_PROXIES` が未設定のとき、アプリは `X-Forwarded-For` を一切信用せず
TCP 接続元のアドレスを使います。設定を忘れると、全アクセスがプロキシの IP として
記録され、IP 制限も意図どおりに効きません。

### 2.6 systemd ユニットの例

```ini
# /etc/systemd/system/bcards.service
[Unit]
Description=名刺一元管理システム
After=network.target postgresql.service

[Service]
User=bcards
WorkingDirectory=/opt/bcards/app
EnvironmentFile=/etc/bcards/env
ExecStart=/opt/bcards/app/.venv/bin/uvicorn bcards.main:app --host 127.0.0.1 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

ワーカーを分ける場合は、`ExecStart` を `/opt/bcards/app/.venv/bin/python worker.py` にした
`bcards-worker.service` を追加し、アプリ側の EnvironmentFile で
`BCARDS_WORKER_ENABLED=0` を指定します。

---

## 3. 環境変数

`/etc/bcards/env`（パーミッションは `600`、所有者はサービス実行ユーザー）に記述します。

### 必須

| 変数 | 例 | 説明 |
| --- | --- | --- |
| `BCARDS_ENV` | `production` | 起動時チェックを厳格にする |
| `BCARDS_DATABASE_URL` | `postgresql+psycopg://bcards:***@db:5432/bcards` | 接続先 |
| `BCARDS_SECRET_KEY` | （48文字以上のランダム文字列） | セッション署名鍵 |
| `BCARDS_SECURE_COOKIE` | `1` | Cookie を HTTPS 限定にする |
| `BCARDS_AUTO_CREATE_TABLES` | `0` | スキーマは Alembic で管理する |
| `BCARDS_TRUSTED_PROXIES` | `127.0.0.1/32` | プロキシの CIDR（カンマ区切り） |

### ストレージ

| 変数 | 既定 | 説明 |
| --- | --- | --- |
| `BCARDS_STORAGE_BACKEND` | `local` | `local` / `s3` |
| `BCARDS_S3_BUCKET` | — | `s3` のとき必須 |
| `BCARDS_S3_KEY_PREFIX` | `business-cards` | バケット内の接頭辞 |
| `BCARDS_S3_REGION` | — | リージョン |
| `BCARDS_S3_ENDPOINT_URL` | — | MinIO 等の S3 互換ストレージ |
| `BCARDS_S3_SSE` | `AES256` | 保存時暗号化。空文字で無効 |
| `BCARDS_STORAGE_QUOTA_BYTES` | `50GiB` | 容量アラートの分母。契約容量を設定する |

S3 の認証情報はアプリに持たせず、インスタンスロール（IAM ロール）で渡す運用を推奨します。
必要な権限は `s3:GetObject` / `s3:PutObject` / `s3:DeleteObject` / `s3:ListBucket` です。

### OCR・取込

| 変数 | 既定 | 説明 |
| --- | --- | --- |
| `BCARDS_OCR_PROVIDER` | `tesseract` | `mock` / `tesseract` / `azure` |
| `BCARDS_OCR_LANGUAGES` | `jpn+jpn_vert+eng` | 縦書き対応のため `jpn_vert` を含める |
| `BCARDS_OCR_THREAD_LIMIT` | `1` | tesseract の OpenMP スレッド数（§5 参照） |
| `BCARDS_OCR_TIMEOUT_SECONDS` | `120` | 1回の OCR の上限。超えたらそのファイルはエラー |
| `BCARDS_FIELD_EXTRACTOR` | `auto` | `rule` / `llm` / `auto` |
| `BCARDS_WORKER_ENABLED` | `1` | アプリ内でワーカーを動かすか |
| `BCARDS_WORKER_CONCURRENCY` | `2` | ワーカー数（§5 参照） |
| `BCARDS_WORKER_LEASE_SECONDS` | `600` | この時間を過ぎた処理中ファイルはキューへ戻す |

### バックアップ

| 変数 | 既定 | 説明 |
| --- | --- | --- |
| `BCARDS_BACKUP_DIR` | `/var/backups/bcards` | バックアップの保存先 |
| `BCARDS_BACKUP_KEEP_DAYS` | `35` | 保持日数 |
| `BCARDS_BACKUP_S3_BUCKET` | — | S3運用時、画像の同期先バケット |

---

## 4. 起動時の設定チェック

`BCARDS_ENV=production` で起動すると、危険な設定を検出して**起動を中止**します。

| 検出内容 | 判定 |
| --- | --- |
| `BCARDS_SECRET_KEY` が既定値 | エラー（起動中止） |
| `BCARDS_SECURE_COOKIE` が無効 | エラー |
| IP 制限が無効（要件§6） | エラー |
| `BCARDS_STORAGE_BACKEND=s3` だがバケット未設定 | エラー |
| `BCARDS_FIELD_EXTRACTOR=llm` だが認証情報なし | エラー |
| 自動テーブル作成が有効 | 警告 |
| SQLite で起動 | 警告 |
| 画像がローカル保存 | 警告 |
| tesseract のスレッド数が無制限で並列ワーカー | 警告 |

エラーはログに出力され、起動時に例外として送出されます。設定を直してから再起動してください。

---

## 5. 取込ワーカーの台数とOCRの並列度

**`BCARDS_OCR_THREAD_LIMIT` は必ず `1`（既定）のままにしてください。**

tesseract は既定で CPU 数ぶんの OpenMP スレッドを使います。ワーカーを複数動かすと
「ワーカー数 × CPU 数」のスレッドが同時に走り、コンテキストスイッチだけで CPU を使い切って
取込がまったく進まなくなります。4 CPU のサーバーでの実測値は次のとおりです。

| 条件 | 同一画像 6 件の処理時間 |
| --- | --- |
| スレッド数無制限 | **10 分経っても完了せず（打ち切り）** |
| `OMP_THREAD_LIMIT=1` | **2.1 秒** |

アプリはこの値を tesseract の子プロセスへ `OMP_THREAD_LIMIT` として渡します。
OCR の精度には影響しません（PoC の正答率 44.8% は設定前後で同一）。

台数の目安:

| サーバーの CPU 数 | `BCARDS_WORKER_CONCURRENCY` |
| --- | --- |
| 2 | 1 |
| 4 | 2（既定） |
| 8 以上 | 4 |

1 枚あたりの処理時間は 4 CPU で約 3 秒です。年間 3,000 枚（要件§3）の想定なら、
まとめて 100 枚取り込んでも既定の 2 ワーカーで 3 分程度で完了します。

なお、OCR 実行中はデータベースのトランザクションを閉じています。閉じないと
PostgreSQL 側に `idle in transaction` の接続が滞留し、VACUUM が進まなくなるためです。
処理の途中でワーカーが落ちた場合、作りかけの取込明細は次の再処理時に自動で片付けられます。

---

## 6. バックアップ

要件§10 のとおり、名刺画像・名刺情報に保存期限はありません。
「消える運用」にならないよう、保持期間は長めに設定してください。

### 取得

```bash
cd /opt/bcards/app
sudo -u bcards env $(cat /etc/bcards/env | xargs) ./ops/backup.sh
```

取得されるもの:

| 対象 | 形式 | 備考 |
| --- | --- | --- |
| データベース | `database.dump`（pg_dump カスタム形式） | 表単位の復元が可能 |
| 画像（ローカル保存時） | `objects.tar.gz` | 内容ハッシュがキーのため既存分は不変 |
| 画像（S3 運用時） | 別バケットへ同期、または同期せず | バージョニング＋レプリケーションに任せる |
| メタ情報 | `manifest.txt` | 取得時刻・スキーマ版・件数 |
| チェックサム | `SHA256SUMS` | 復元時に自動検証 |

### 定期実行

```cron
# /etc/cron.d/bcards-backup
0 2 * * * bcards . /etc/bcards/env; /opt/bcards/app/ops/backup.sh >> /var/log/bcards-backup.log 2>&1
```

### 世代管理の考え方

| 種類 | 頻度 | 保持 |
| --- | --- | --- |
| 日次 | 毎日 02:00 | 35 日（`BCARDS_BACKUP_KEEP_DAYS`） |
| 月次 | 月初のものを別領域へ退避 | 5 年以上（保存期限なしのため） |

バックアップの保存先は、アプリサーバーとは別の障害単位（別リージョン・別アカウント）に
置いてください。ランサムウェア対策として、書き込み後に変更できない設定
（S3 のオブジェクトロック等）の利用を推奨します。

---

## 7. 復元と復元訓練

### 手順

```bash
cd /opt/bcards/app

# 1. 復元先を用意する（本番へ直接戻す場合はこの手順は不要）
sudo -u postgres createdb bcards_restore --owner bcards

# 2. 復元する（--force がなければ確認を求める）
BCARDS_DATABASE_URL="postgresql+psycopg://bcards:***@db:5432/bcards_restore" \
  ./ops/restore.sh /var/backups/bcards/20260728T020000Z

# 3. スキーマがアプリより古い場合は追随させる
BCARDS_DATABASE_URL="postgresql+psycopg://bcards:***@db:5432/bcards_restore" \
  .venv/bin/alembic upgrade head

# 4. 画像の実体が揃っているか確認する
BCARDS_DATABASE_URL="postgresql+psycopg://bcards:***@db:5432/bcards_restore" \
  .venv/bin/python ops/verify.py
```

`ops/verify.py` は、DB に登録されている画像レコードに対して実体がストレージにあるかを確認し、
欠損があれば終了コード `1` を返します。「DB は戻ったが画像が戻っていない」状態を検出できます。

### 復元訓練

バックアップは「取れていること」ではなく「戻せること」を確認して初めて意味があります。
**四半期に 1 回**、上記手順を復元用データベースに対して実行し、次を記録してください。

- 復元にかかった時間
- `ops/verify.py` の結果
- 復元後にアプリを起動して名刺一覧・画像表示・CSV 出力が動作すること

---

## 8. スキーマ変更（マイグレーション）

```bash
# 現在の版を確認する
.venv/bin/alembic current

# 未適用のマイグレーションを確認する
.venv/bin/alembic history --indicate-current

# 適用する（実行前に必ずバックアップを取得する）
./ops/backup.sh
.venv/bin/alembic upgrade head
```

モデルを変更したあとの手順:

```bash
.venv/bin/alembic revision --autogenerate -m "変更内容"
# 生成されたファイルを必ず目視で確認し、制約名などを補う
.venv/bin/alembic upgrade head
.venv/bin/alembic downgrade -1 && .venv/bin/alembic upgrade head   # 往復できることを確認する
```

自動生成は取りこぼしがあります。特に、列の削除・型変更・データ移行を伴う変更は
手で書き足してください。

---

## 9. 監視項目

| 項目 | 確認方法 | 閾値の目安 |
| --- | --- | --- |
| 取込キューの滞留 | 管理画面「取込状況」／`import_file` の `queued` 件数 | 100 件以上が 10 分継続 |
| 処理中のまま止まった取込 | `import_file` の `processing` かつ `locked_at` が古い | `BCARDS_WORKER_LEASE_SECONDS` 経過で自動回収 |
| ストレージ使用率 | 管理画面「保存容量」 | 80% で警告 |
| `idle in transaction` | `pg_stat_activity` | 常時 0 件であるべき |
| ログイン失敗 | `login_attempt` テーブル | 同一アカウントで連続 5 回 |
| バックアップの成否 | `/var/log/bcards-backup.log` | 失敗を検知したら通知 |

滞留の確認:

```sql
SELECT status, count(*) FROM import_file GROUP BY status;
SELECT source_file_name, attempts, locked_by, locked_at
  FROM import_file WHERE status = 'processing' ORDER BY locked_at;
```

---

## 10. 障害時の対応

### 取込が進まない

1. `BCARDS_OCR_THREAD_LIMIT` が `1` になっているか確認する（§5）。最も多い原因です。
2. ワーカーが動いているか確認する（`systemctl status bcards-worker` またはアプリのログ）。
3. `import_file` に `processing` のまま残っている行がないか確認する。
   ワーカーが落ちた場合は `BCARDS_WORKER_LEASE_SECONDS`（既定 10 分）経過後に自動でキューへ戻り、
   3 回失敗した時点でエラーとして確定します。

### OCR がエラーになる

取込明細はエラー状態で残るため、確認画面から再処理できます（要件§8）。
画像そのものが読めない場合は、確認画面で手入力に切り替えられます。

### データベースに接続できない

アプリは接続前に疎通確認を行い（`pool_pre_ping`）、切れた接続を自動で捨てます。
DB 復旧後はアプリの再起動なしで回復します。

### 画像が表示されない

`ops/verify.py` で実体の欠損を確認してください。
欠損していた場合はバックアップから該当キーのオブジェクトのみ復元できます
（キーは内容ハッシュのため、上書きしても既存データを壊しません）。
