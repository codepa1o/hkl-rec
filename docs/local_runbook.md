# NewsIntentRec 本地运行手册

## 前置条件

- Python 3.13
- 支持 Compose 的 Docker
- Node.js 20+

```bash
python -m venv .venv
.venv/bin/python -m pip install -r backend/requirements-dev.txt
cd product-frontend && npm ci && cd ..
```

## 初始化

```bash
PYTHON=.venv/bin/python scripts/init_local.sh --product-frontend
```

使用 `--smoke-test` 执行一次性检查；使用 `--with-kafka` 启动 Kafka、
画像消费者和 Outbox 发布器。

关键变量：

- `NEWSREC_DATABASE_URL`
- `NEWSREC_DEMO_SEED_DIR`（默认值 `build/mind_demo_world`）
- `NEWSREC_MODEL_DIR`（默认值 `build/mind_models`）
- `NEWSREC_SEARCH_RETRIEVAL_MODE`（默认值 `hybrid_v1`）
- `NEWSREC_SEARCH_INDEX_DIR`（默认值 `build/mind_search/demo`）
- `NEWSREC_EVENT_MODE`
- `NEWSREC_KAFKA_*`
- `VITE_NEWSREC_API_BASE`

在一个迁移周期内仍接受 `ZHIHUREC_*` 别名，并会记录弃用日志。

## 重建数据和模型

```bash
python scripts/download_mind.py --variant small --split all --accept-license --source huyva
python scripts/inspect_mind.py --variant small
python scripts/normalize_mind.py
python scripts/build_mind_demo_world.py
python scripts/build_search_index.py \
  --corpus full \
  --model-revision 1110a243fdf4706b3f48f1d95db1a4f5529b4d41 \
  --config evaluation/search_relevance/selected_config.json
python scripts/calibrate_search_relevance.py
python scripts/eval_search_relevance.py \
  --config evaluation/search_relevance/selected_config.json
python scripts/build_search_index.py \
  --corpus demo \
  --model-revision 1110a243fdf4706b3f48f1d95db1a4f5529b4d41 \
  --config evaluation/search_relevance/selected_config.json \
  --online-config evaluation/search_relevance/online_demo_config.json
python scripts/import_demo_world.py \
  --input-dir build/mind_demo_world \
  --output-sql build/mind_demo_world/import_demo_world.sql \
  --truncate-first
python scripts/train_eval_mind.py
python scripts/report_mind_data.py
```

## 手动启动服务

```bash
docker compose up -d
export NEWSREC_DATABASE_URL='mysql+pymysql://root:root@127.0.0.1:3307/newsrec_demo'
python scripts/apply_demo_mysql.py
python scripts/build_search_index.py \
  --corpus demo \
  --model-revision 1110a243fdf4706b3f48f1d95db1a4f5529b4d41 \
  --config evaluation/search_relevance/selected_config.json \
  --online-config evaluation/search_relevance/online_demo_config.json
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

使用 Kafka 时：

```bash
docker compose -f docker-compose.kafka.yml up -d
docker compose -f docker-compose.kafka.yml run --rm kafka-init
export NEWSREC_EVENT_MODE=kafka_async
export NEWSREC_KAFKA_BOOTSTRAP_SERVERS=127.0.0.1:9092
python scripts/run_profile_consumer.py
python scripts/run_outbox_publisher.py
```

## 验证

```bash
python -m ruff check backend scripts tests
python -m mypy
python -m pytest -q
cd product-frontend && npm test -- --run && npm run build
```

健康检查端点包括 `/livez`、`/readyz`、`/healthz` 和 `/metrics`。
启用混合搜索时，就绪检查还会验证搜索制品指纹、文件哈希、FAISS 行数和本地缓存的编码器修订号。
