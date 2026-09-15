# NewsIntentRec 本地运行手册

## 前置条件

- Python 3.13
- 支持 Compose 的 Docker
- Node.js 20+

```bash
python -m venv .venv
.venv/bin/python -m pip install -r backend/requirements-dev.txt
npm --prefix product-frontend ci
```

## 一键初始化

Linux/macOS：

```bash
BUILD_SEARCH_INDEX=1 scripts/init_local.sh
```

Windows PowerShell：

```powershell
./scripts/init_local.ps1 -BuildSearchIndex
```

初始化会启动 PostgreSQL、升级 Alembic、下载 MIND-small train/dev、生成规范化 Parquet、
把全部 65,238 篇唯一新闻导入数据库，并按需构建全目录混合搜索索引。下载操作表示你已阅读并
接受 MIND 数据许可；原始数据、Parquet 和索引均只保存在本地。

在线新闻事实只落在八字段 `mind_news`；`mind_news_stats` 是训练统计，`mind_news_topic` 是
严格的两条 category/subcategory 关联，`mind_catalog_import` 是指纹与行数证明。这些辅助表
不复制或改写 MIND 新闻正文。

首页使用每批 20 篇的游标式无限滚动。分页会话状态只保存在 `feed_request`，不会改变
`mind_news` 的八字段结构。详情接口解析两个实体 JSON 字段，页面只在文章详情中展示人物、
机构、地点和其他实体。

关键变量：

- `NEWSREC_DATABASE_URL`
- `NEWSREC_MIND_NORMALIZED_DIR`（默认 `build/mind_normalized`）
- `NEWSREC_SEARCH_RETRIEVAL_MODE`（默认 `hybrid_v1`）
- `NEWSREC_SEARCH_INDEX_DIR`（默认 `build/mind_search/full`）
- `NEWSREC_DEFAULT_DEMO_USER_ID`（默认 `7001`）
- `NEWSREC_MODEL_DIR`（默认 `build/mind_models`）
- `NEWSREC_EVENT_MODE`
- `NEWSREC_KAFKA_*`
- `VITE_NEWSREC_API_BASE`

## 分阶段重建

```bash
docker compose up -d --wait postgres
export NEWSREC_DATABASE_URL='postgresql+psycopg://newsrec:newsrec@127.0.0.1:5432/newsrec_demo'
python -m alembic upgrade head
python scripts/download_mind.py --variant small --split all --accept-license --source huyva
python scripts/inspect_mind.py --variant small
python scripts/normalize_mind.py
python scripts/import_mind_catalog.py \
  --normalized-root build/mind_normalized \
  --replace-catalog
python scripts/build_search_index.py \
  --input-dir build/mind_normalized \
  --output-dir build/mind_search/full \
  --model-revision 1110a243fdf4706b3f48f1d95db1a4f5529b4d41 \
  --config evaluation/search_relevance/selected_config.json
python scripts/train_eval_mind.py
python scripts/report_mind_data.py
```

`--replace-catalog` 会替换现有 MIND 新闻目录；对重要数据库执行前应先用 `pg_dump -Fc` 备份。
导入器会校验 Parquet 清单、源指纹、唯一 `news_id`、新闻/统计行数和训练曝光/点击总数，失败时
整个事务回滚。

## 手动启动服务

```bash
export NEWSREC_MIND_NORMALIZED_DIR=build/mind_normalized
export NEWSREC_SEARCH_INDEX_DIR=build/mind_search/full
export NEWSREC_SEARCH_RETRIEVAL_MODE=hybrid_v1
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

使用 Kafka 时：

```bash
docker compose -f docker-compose.kafka.yml up -d --wait
docker compose -f docker-compose.kafka.yml run --rm kafka-init
export NEWSREC_EVENT_MODE=kafka_async
export NEWSREC_KAFKA_BOOTSTRAP_SERVERS=127.0.0.1:9092
python scripts/run_profile_consumer.py
python scripts/run_outbox_publisher.py
```

## 验证

```bash
python -m pip check
python -m ruff check backend scripts tests
python -m ruff format --check backend scripts tests
python -m mypy
python -m pytest -q
npm --prefix product-frontend test -- --run
npm --prefix product-frontend run build
```

健康检查端点包括 `/livez`、`/readyz`、`/healthz` 和 `/metrics`。启用混合搜索时，就绪检查会
验证规范化数据指纹、搜索制品哈希、FAISS 行数和编码器修订号。

## 中文实时新闻本地研究全文

新华网、人民网和中新网的正文采集仅供本机、论文和非公开演示。默认关闭；生产环境即使把
开关设为 `1`，API 也不会返回 `local_research` 正文。澎湃新闻继续保持原文链接模式。

启用前先迁移数据库并重建两个 Worker：

```powershell
$env:NEWSREC_ENVIRONMENT='development'
$env:NEWSREC_LOCAL_RESEARCH_FULLTEXT_ENABLED='1'
docker compose up -d --build db-migrate live-news-collector live-content-worker
```

先对单一来源做最多 20 篇 dry-run：

```powershell
python scripts/backfill_live_structured_content.py `
  --language zh `
  --source-suffix xinhuanet.com `
  --since-days 7 `
  --limit 20 `
  --dry-run
```

去掉 `--dry-run` 只会把候选文章加入正文任务队列，实际抓取由 `live-content-worker` 完成。
观察日志和数据库中的成功率、失败码、正文长度与结构块数量后再逐步扩大。不得绕过发布方的
登录、验证码、403 或反爬限制，也不得将该模式部署给公网普通用户。
