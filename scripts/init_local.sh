#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

export NEWSREC_DATABASE_URL="${NEWSREC_DATABASE_URL:-postgresql+psycopg://newsrec:newsrec@127.0.0.1:5432/newsrec_demo}"
export NEWSREC_MIND_NORMALIZED_DIR="${NEWSREC_MIND_NORMALIZED_DIR:-build/mind_normalized}"
export NEWSREC_SEARCH_INDEX_DIR="${NEWSREC_SEARCH_INDEX_DIR:-build/mind_search/full}"

python -m pip install -r backend/requirements-dev.txt
npm --prefix product-frontend ci
docker compose up -d --wait postgres
python -m alembic upgrade head
python scripts/download_mind.py --variant small --split all --accept-license --source huyva
python scripts/normalize_mind.py
python scripts/import_mind_catalog.py --normalized-root build/mind_normalized --replace-catalog
python scripts/reset_demo_user.py --user-count 3
python scripts/seed_demo_sponsored.py

if [[ "${BUILD_SEARCH_INDEX:-0}" == "1" ]]; then
  python scripts/build_search_index.py \
    --input-dir build/mind_normalized \
    --output-dir build/mind_search/full \
    --config evaluation/search_relevance/selected_config.json
fi

echo "Local PostgreSQL and the full MIND-small catalog are ready."
