param(
    [switch]$SkipInstall,
    [switch]$SkipData,
    [switch]$BuildSearchIndex
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot

if (-not $env:NEWSREC_DATABASE_URL) {
    $env:NEWSREC_DATABASE_URL = 'postgresql+psycopg://newsrec:newsrec@127.0.0.1:5432/newsrec_demo'
}
$env:NEWSREC_MIND_NORMALIZED_DIR = 'build/mind_normalized'
$env:NEWSREC_SEARCH_INDEX_DIR = 'build/mind_search/full'

if (-not $SkipInstall) {
    python -m pip install -r backend/requirements-dev.txt
    Push-Location product-frontend
    try { npm ci } finally { Pop-Location }
}

docker compose up -d --wait postgres
python -m alembic upgrade head

if (-not $SkipData) {
    python scripts/download_mind.py --variant small --split all --accept-license --source huyva
    python scripts/normalize_mind.py
    python scripts/import_mind_catalog.py --normalized-root build/mind_normalized --replace-catalog
    if ($BuildSearchIndex) {
        python scripts/build_search_index.py `
            --input-dir build/mind_normalized `
            --output-dir build/mind_search/full `
            --config evaluation/search_relevance/selected_config.json
    }
}

python scripts/reset_demo_user.py --user-count 3
python scripts/seed_demo_sponsored.py

Write-Host 'Local PostgreSQL and the full MIND-small catalog are ready.'
