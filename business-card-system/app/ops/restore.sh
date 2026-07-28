#!/usr/bin/env bash
#
# 名刺一元管理システム 復元スクリプト
#
#   ./ops/restore.sh <バックアップディレクトリ> [--force]
#
# 既定では BCARDS_DATABASE_URL の指すデータベースへ復元する。
# 誤って本番へ流し込まないよう、--force がなければ確認を求める。
#
# 復元は必ず「バックアップが実際に戻せるか」の訓練を兼ねて定期的に実施する
# （operations-guide.md「復元訓練」）。

set -euo pipefail

SRC="${1:?バックアップディレクトリを指定してください}"
FORCE="${2:-}"

: "${BCARDS_DATABASE_URL:?BCARDS_DATABASE_URL を設定してください}"
PG_URL="${BCARDS_DATABASE_URL/postgresql+psycopg:/postgresql:}"

[[ -f "${SRC}/database.dump" ]] || { echo "database.dump が見つかりません: ${SRC}" >&2; exit 2; }

echo "--- 復元しようとしているバックアップ ---"
cat "${SRC}/manifest.txt" 2>/dev/null || echo "(manifest.txt なし)"
echo "--- 復元先 ---"
echo "${PG_URL%%\?*}"
echo

if [[ -f "${SRC}/SHA256SUMS" ]]; then
  echo "チェックサムを検証しています..."
  ( cd "${SRC}" && sha256sum --check --quiet SHA256SUMS ) && echo "OK"
fi

if [[ "${FORCE}" != "--force" ]]; then
  read -r -p "上記のデータベースの内容を置き換えます。よろしいですか？ [yes/NO] " answer
  [[ "${answer}" == "yes" ]] || { echo "中止しました。"; exit 1; }
fi

echo "[1/3] データベースを復元しています..."
# --clean --if-exists で既存オブジェクトを落としてから入れ直す
pg_restore --dbname="${PG_URL}" --clean --if-exists --no-owner --no-privileges "${SRC}/database.dump"

echo "[2/3] 画像を復元しています..."
if [[ -f "${SRC}/objects.tar.gz" ]]; then
  STORAGE_DIR="${BCARDS_STORAGE_DIR:-$(cd "$(dirname "$0")/.." && pwd)/storage/objects}"
  mkdir -p "$(dirname "${STORAGE_DIR}")"
  tar -C "$(dirname "${STORAGE_DIR}")" -xzf "${SRC}/objects.tar.gz"
  echo "      ${STORAGE_DIR}"
else
  echo "      objects.tar.gz なし（S3運用のためスキップ）"
fi

echo "[3/3] 整合性を確認しています..."
psql --dbname="${PG_URL}" -tAc "SELECT 'business_card=' || count(*) FROM business_card"
psql --dbname="${PG_URL}" -tAc "SELECT 'card_image=' || count(*) FROM card_image"
psql --dbname="${PG_URL}" -tAc "SELECT 'alembic=' || version_num FROM alembic_version"
echo
echo "スキーマがアプリより古い場合は alembic upgrade head を実行してください。"
echo "復元後は ops/verify.py で画像の実体が揃っているか確認できます。"
