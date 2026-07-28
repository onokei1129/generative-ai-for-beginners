#!/usr/bin/env bash
#
# 名刺一元管理システム バックアップ取得スクリプト
#
#   ./ops/backup.sh [出力先ディレクトリ]
#
# データベース（PostgreSQL）と、ローカル保存時のオブジェクトを取得する。
# オブジェクトストレージに S3 を使っている場合は、DBのみを取得し、
# 画像は S3 のバージョニング＋レプリケーションに任せる（operations-guide.md 参照）。
#
# 要件§5「バックアップデータ」「バックアップ領域」に対応する。
# 名刺画像・名刺情報に保存期限はない（要件§10）ため、
# 世代管理は「消える運用」にならないよう保持日数を長めに設定する。

set -euo pipefail

BACKUP_ROOT="${1:-${BCARDS_BACKUP_DIR:-/var/backups/bcards}}"
KEEP_DAYS="${BCARDS_BACKUP_KEEP_DAYS:-35}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
DEST="${BACKUP_ROOT}/${STAMP}"

: "${BCARDS_DATABASE_URL:?BCARDS_DATABASE_URL を設定してください}"

if [[ "${BCARDS_DATABASE_URL}" != postgresql* ]]; then
  echo "このスクリプトは PostgreSQL 用です: ${BCARDS_DATABASE_URL%%://*}" >&2
  exit 2
fi

# SQLAlchemy 形式（postgresql+psycopg://）を libpq が読める形に直す
PG_URL="${BCARDS_DATABASE_URL/postgresql+psycopg:/postgresql:}"

mkdir -p "${DEST}"
echo "バックアップ先: ${DEST}"

# --- データベース -----------------------------------------------------------
# -Fc（カスタム形式）は pg_restore で表単位の復元ができる
echo "[1/3] データベースを取得しています..."
pg_dump --dbname="${PG_URL}" --format=custom --compress=9 --file="${DEST}/database.dump"
echo "      $(du -h "${DEST}/database.dump" | cut -f1)"

# --- オブジェクト（画像） ---------------------------------------------------
echo "[2/3] 画像を取得しています..."
BACKEND="${BCARDS_STORAGE_BACKEND:-local}"
if [[ "${BACKEND}" == "local" ]]; then
  STORAGE_DIR="${BCARDS_STORAGE_DIR:-$(cd "$(dirname "$0")/.." && pwd)/storage/objects}"
  # 内容ハッシュがキーなので、既存ファイルは変化しない。差分同期で足りる
  tar -C "$(dirname "${STORAGE_DIR}")" -czf "${DEST}/objects.tar.gz" "$(basename "${STORAGE_DIR}")"
  echo "      $(du -h "${DEST}/objects.tar.gz" | cut -f1)"
elif [[ "${BACKEND}" == "s3" ]]; then
  : "${BCARDS_S3_BUCKET:?BCARDS_S3_BUCKET を設定してください}"
  if [[ -n "${BCARDS_BACKUP_S3_BUCKET:-}" ]]; then
    aws s3 sync "s3://${BCARDS_S3_BUCKET}/${BCARDS_S3_KEY_PREFIX:-business-cards}" \
                "s3://${BCARDS_BACKUP_S3_BUCKET}/objects" --only-show-errors
    echo "      s3://${BCARDS_BACKUP_S3_BUCKET}/objects へ同期しました"
  else
    echo "      S3のためスキップ（バージョニングとレプリケーションで保全する運用）"
  fi
else
  echo "未知のストレージ実装です: ${BACKEND}" >&2
  exit 2
fi

# --- 検証用メタ情報 ---------------------------------------------------------
echo "[3/3] メタ情報を記録しています..."
{
  echo "taken_at=${STAMP}"
  echo "storage_backend=${BACKEND}"
  echo "alembic_revision=$(psql --dbname="${PG_URL}" -tAc 'SELECT version_num FROM alembic_version' 2>/dev/null || echo unknown)"
  echo "card_count=$(psql --dbname="${PG_URL}" -tAc 'SELECT count(*) FROM business_card' 2>/dev/null || echo unknown)"
  echo "card_image_count=$(psql --dbname="${PG_URL}" -tAc 'SELECT count(*) FROM card_image' 2>/dev/null || echo unknown)"
} > "${DEST}/manifest.txt"
( cd "${DEST}" && sha256sum ./* > SHA256SUMS 2>/dev/null || true )
cat "${DEST}/manifest.txt"

# --- 世代管理 ---------------------------------------------------------------
find "${BACKUP_ROOT}" -mindepth 1 -maxdepth 1 -type d -mtime "+${KEEP_DAYS}" -print -exec rm -rf {} +

echo "完了しました: ${DEST}"
