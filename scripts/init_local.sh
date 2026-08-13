#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

python_bin="${PYTHON:-python3}"
if [[ -z "${NEWSREC_DATABASE_URL:-}" && -n "${ZHIHUREC_DATABASE_URL:-}" ]]; then
  echo "deprecated environment variable ZHIHUREC_DATABASE_URL; use NEWSREC_DATABASE_URL" >&2
fi
if [[ -z "${NEWSREC_EVENT_MODE:-}" && -n "${ZHIHUREC_EVENT_MODE:-}" ]]; then
  echo "deprecated environment variable ZHIHUREC_EVENT_MODE; use NEWSREC_EVENT_MODE" >&2
fi
if [[ -z "${NEWSREC_KAFKA_BOOTSTRAP_SERVERS:-}" && -n "${ZHIHUREC_KAFKA_BOOTSTRAP_SERVERS:-}" ]]; then
  echo "deprecated environment variable ZHIHUREC_KAFKA_BOOTSTRAP_SERVERS; use NEWSREC_KAFKA_BOOTSTRAP_SERVERS" >&2
fi
database_url="${NEWSREC_DATABASE_URL:-${ZHIHUREC_DATABASE_URL:-mysql+pymysql://root:root@127.0.0.1:3307/newsrec_demo}}"
backend_port="${NEWSREC_BACKEND_PORT:-${ZHIHUREC_BACKEND_PORT:-8000}}"
product_frontend_port="${NEWSREC_PRODUCT_FRONTEND_PORT:-${ZHIHUREC_PRODUCT_FRONTEND_PORT:-5174}}"
smoke_test=0
product_frontend=0
with_kafka=0
event_mode="${NEWSREC_EVENT_MODE:-${ZHIHUREC_EVENT_MODE:-kafka_dual_write}}"
runtime_dir="$repo_root/.runtime/init_local"
declare -a started_pids=()

usage() {
  cat <<'EOF'
Usage: scripts/init_local.sh [options]
  --smoke-test          验证整个技术栈并停止子进程。
  --product-frontend    启动 React/Vite 前端。
  --with-kafka          启动 Kafka、画像消费者和 Outbox 发布器。
  --event-mode MODE     kafka_dual_write 或 kafka_async（默认双写）。
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --smoke-test) smoke_test=1 ;;
    --product-frontend) product_frontend=1 ;;
    --with-kafka) with_kafka=1 ;;
    --event-mode)
      shift
      event_mode="${1:?--event-mode requires a value}"
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

mkdir -p "$runtime_dir"

cleanup() {
  local pid
  for pid in "${started_pids[@]:-}"; do
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
    fi
  done
}
trap cleanup EXIT INT TERM

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "Required command not found: $1" >&2
    exit 1
  }
}

wait_container() {
  local container="$1"
  local deadline=$((SECONDS + 120))
  while (( SECONDS < deadline )); do
    if [[ "$(docker inspect -f '{{.State.Health.Status}}' "$container" 2>/dev/null || true)" == "healthy" ]]; then
      return 0
    fi
    sleep 2
  done
  echo "Container did not become healthy: $container" >&2
  exit 1
}

start_service() {
  local name="$1"
  shift
  "$@" >"$runtime_dir/$name.out.log" 2>"$runtime_dir/$name.err.log" &
  local pid=$!
  started_pids+=("$pid")
  sleep 1
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "$name exited during startup" >&2
    tail -n 30 "$runtime_dir/$name.err.log" >&2 || true
    exit 1
  fi
  echo "$name pid=$pid"
}

require_command "$python_bin"
require_command docker
require_command curl
docker compose version >/dev/null

echo "[1/6] Starting MySQL"
docker compose up -d
wait_container newsrec-mysql

if (( with_kafka )); then
  echo "[2/6] Starting Kafka"
  docker compose -f docker-compose.kafka.yml up -d
  wait_container newsrec-kafka
  export NEWSREC_EVENT_MODE="$event_mode"
  export NEWSREC_KAFKA_BOOTSTRAP_SERVERS="${NEWSREC_KAFKA_BOOTSTRAP_SERVERS:-${ZHIHUREC_KAFKA_BOOTSTRAP_SERVERS:-127.0.0.1:9092}}"
else
  echo "[2/6] Kafka disabled"
  export NEWSREC_EVENT_MODE=sync_mysql
fi

export NEWSREC_DATABASE_URL="$database_url"
export NEWSREC_DEMO_SEED_DIR="${NEWSREC_DEMO_SEED_DIR:-build/mind_demo_world}"
export NEWSREC_SPONSORED_ENABLED="${NEWSREC_SPONSORED_ENABLED:-${ZHIHUREC_SPONSORED_ENABLED:-1}}"
export NEWSREC_SEARCH_RETRIEVAL_MODE="${NEWSREC_SEARCH_RETRIEVAL_MODE:-hybrid_v1}"
export NEWSREC_SEARCH_INDEX_DIR="${NEWSREC_SEARCH_INDEX_DIR:-build/mind_search/demo}"

echo "[3/6] Applying schema and demo seed"
"$python_bin" scripts/apply_demo_mysql.py
"$python_bin" scripts/reset_demo_user.py
if [[ "$NEWSREC_SEARCH_RETRIEVAL_MODE" == "hybrid_v1" ]]; then
  "$python_bin" scripts/build_search_index.py \
    --corpus demo \
    --input-dir "$NEWSREC_DEMO_SEED_DIR" \
    --output-dir "$NEWSREC_SEARCH_INDEX_DIR" \
    --config evaluation/search_relevance/selected_config.json \
    --online-config evaluation/search_relevance/online_demo_config.json
fi

echo "[4/6] Starting backend and workers"
start_service backend "$python_bin" -m uvicorn backend.app.main:app \
  --host 127.0.0.1 --port "$backend_port"
if (( with_kafka )); then
  start_service outbox "$python_bin" scripts/run_outbox_publisher.py
  start_service consumer "$python_bin" scripts/run_profile_consumer.py
fi

echo "[5/6] Starting product frontend"
if (( product_frontend )); then
  require_command npm
  if [[ ! -d product-frontend/node_modules ]]; then
    (cd product-frontend && npm ci)
  fi
  (
    cd product-frontend
    exec npm run dev -- --host 127.0.0.1 --port "$product_frontend_port"
  ) >"$runtime_dir/product-frontend.out.log" 2>"$runtime_dir/product-frontend.err.log" &
  started_pids+=("$!")
fi

echo "[6/6] Running smoke checks"
"$python_bin" scripts/smoke_local.py \
  --base-url "http://127.0.0.1:$backend_port" \
  --timeout-seconds 90

echo "Ready: backend=http://127.0.0.1:$backend_port"
if (( product_frontend )); then
  echo "Product frontend: http://127.0.0.1:$product_frontend_port"
fi

if (( smoke_test )); then
  echo "Smoke test passed."
  exit 0
fi

echo "Press Ctrl+C to stop processes started by this script."
while true; do
  for pid in "${started_pids[@]}"; do
    if ! kill -0 "$pid" 2>/dev/null; then
      if wait "$pid"; then
        status=0
      else
        status=$?
      fi
      echo "A managed process exited with status $status" >&2
      exit "$status"
    fi
  done
  sleep 2
done
