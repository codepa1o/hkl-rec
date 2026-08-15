# NewsIntentRec

基于**公开 Microsoft MIND 数据集**构建的个性化新闻推荐系统。
本项目不是 Microsoft 产品或实习交付物，也未使用 Microsoft 内部的数据、代码、模型或基础设施。

MIND 提供真实的文章曝光、已曝光未点击项、点击项以及请求前的历史记录，但**不提供用户搜索日志**。
本项目中的搜索是一种本地产品反馈机制；`docs/metrics/mind_intent_mechanism.json`
仅用于展示机制行为，不能作为点击率或用户因果收益的证据。

## 已实现功能

- 带校验和与指纹的确定性 MIND 下载、检查和规范化流程；
- 基于真实曝光负样本、感知曝光且按请求级时间顺序执行的评估；
- ALS + FAISS 协同召回，以及明确的未知用户回退方案；
- LightGBM 排序、热度/类别基线，以及如实记录的正负消融实验；
- 位于非默认信息流实验分组后的 ALS/主题混合 MMR 重排；
- 精确别名 + BM25 + sentence-transformer/FAISS 混合搜索，并带校准后的拒绝机制；
- FastAPI + PostgreSQL 在线服务、Alembic 迁移、Outbox/Kafka、幂等消费者、健康检查与指标；
- React 信息流/搜索界面、来源/类别标签、用户画像与推荐解释；
- Argon2 密码哈希、HttpOnly Cookie 会话、登录注册和受保护前端路由；
- 相互独立的全量数据模型证据与紧凑、确定性的在线服务/CI 数据世界。

## 当前证据

规范化数据指纹：
`643c53b0ce5fddf5e08a8d6f8e491ddec607a3f56c335c44d872e6e74cbd4b52`。

排序报告在 MIND-small 训练集内部采用全局时间顺序留出法。
LightGBM 使用 20,000 个完整训练请求和 10,000 个完整评估请求。

| 实验分组 | Recall@10 | NDCG@10 | MRR |
|---|---:|---:|---:|
| 热度基线 | 0.4831 | 0.2541 | 0.2167 |
| 手工类别画像 | 0.5027 | 0.2703 | 0.2334 |
| LightGBM | **0.5969** | **0.3628** | **0.3293** |
| LightGBM + MMR (`penalty=0.02`) | 0.5956 | 0.3626 | 0.3296 |
| ALS 调整后的 LightGBM | 0.5967 | 0.3627 | 0.3292 |

在抽样评估中，ALS 未能在 LightGBM 基础上提升 Recall@10。其全目录候选 Recall@50
为 0.0262，因此项目保留了这一负面结果。官方开发集中的已知用户覆盖率为 11.44%；
对 8,902 个抽样冷启动请求，未知用户的内容/类别回退方案 Recall@10 为 0.5568。

选定的 MMR 分组将混合列表内相似度@10 从 `0.2433` 降至 `0.1935`，
将主题覆盖率@10 从 `11.9145` 提升至 `12.9051`；Recall@10 则从 `0.5969`
变为 `0.5956`（绝对变化 `-0.00125`，处于预先声明的 `0.005` 护栏内）。
这只是对已曝光候选项进行重排的证据，并非端到端候选召回、点击率或因果增益结论，
因此该分组仍不是默认选项。

搜索相关性评估包含 48 个固定查询，以及针对全部 65,238 篇规范化文章汇总的
1,239 条标注。标注由 AI 辅助生成，并由用户批准了 12 条分层抽样复核结果。

| 搜索分组 | Recall@10 | NDCG@10 | MRR@10 | OOD 拒绝准确率 |
|---|---:|---:|---:|---:|
| 旧版词法搜索 | 0.2895 | 0.2854 | 0.3158 | 0.0 |
| BM25 | 0.6847 | 0.6790 | 0.7444 | 1.0 |
| 稠密检索 | **0.8806** | **0.8319** | **0.8772** | 1.0 |
| 混合检索 | 0.8122 | 0.8131 | 0.8596 | 1.0 |

混合检索通过了冻结的上线门槛，并在拼写/噪声查询上表现最好，因此被设为默认方案。
稠密检索是整体留出评估中最强的分组；项目保留了这一对混合检索不利的结果，而未将其隐藏。

现有信息流本地回环测量的 p50/p95 为 9.47/14.18 ms。在包含 174 篇文档的演示索引上，
进程内混合检索预热后的测量结果为 6.433/9.568 ms。这些仅是本地测量值，
不代表生产环境容量。

## 数据准备

请阅读 [Microsoft Research 许可条款](https://github.com/msnews/MIND/blob/master/MSR%20License_Data.pdf)。
MIND 官方页面当前会将下载请求转至需要授权的 Hugging Face 访问入口。
下载器要求明确接受许可，并支持该来源或显式选定的公开原始文件镜像：

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
```

原始 MIND 文件、规范化 Parquet、演示包和模型二进制文件均保留在本地，不提交到仓库。

## 本地初始化

```bash
python -m pip install -r backend/requirements-dev.txt
PYTHON=.venv/bin/python scripts/init_local.sh --product-frontend
```

`docker-compose.yml` 默认启动 PostgreSQL 16，应用启动前必须把 Alembic 升级到最新版本：

```bash
docker compose up -d --wait postgres
python -m alembic upgrade head
```

旧 MySQL 只作为一次性历史数据源保留在 `docker-compose.mysql-legacy.yml`。首次切换时，在空的
PostgreSQL 目标库执行以下命令；脚本会在单一目标事务内迁移全部表，并逐表核对行数与内容摘要：

```bash
docker compose -f docker-compose.mysql-legacy.yml up -d --wait mysql
NEWSREC_MYSQL_SOURCE_URL='mysql+pymysql://root:root@127.0.0.1:3307/newsrec_demo' \
NEWSREC_DATABASE_URL='postgresql+psycopg://newsrec:newsrec@127.0.0.1:5432/newsrec_demo' \
python scripts/migrate_mysql_to_postgres.py
```

随后生成至少 32 字符的随机鉴权密钥并写入 `.env`：

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
NEWSREC_AUTH_SECRET_KEY='<generated-secret>'
```

生产环境通过 HTTPS 提供服务时还必须设置 `NEWSREC_AUTH_COOKIE_SECURE=1`。登录注册接口为
`POST /auth/register`、`POST /auth/login`、`GET /auth/me` 和 `POST /auth/logout`；浏览器会话
使用 HttpOnly Cookie，前端不保存或读取 JWT。设置鉴权密钥后，推荐、搜索、文章、画像和
  事件业务接口也会要求有效会话。未设置密钥时默认拒绝业务 API；仅离线研究脚本可显式设置
  `NEWSREC_ALLOW_UNAUTHENTICATED_RESEARCH_API=1` 临时兼容，产品部署禁止开启。

添加 `--smoke-test` 可执行一次性检查，添加 `--with-kafka` 可启动 Kafka 工作进程。
默认数据库为 `newsrec_demo`，种子目录为 `build/mind_demo_world`，
公共 API 使用文章字段和 `/articles/{article_id}`。

## 开发质量门禁

```bash
python -m ruff check backend scripts tests
python -m mypy
python -m pytest -q

cd product-frontend
npm ci
npm test -- --run
npm run build
```

PostgreSQL、MySQL→PostgreSQL 历史迁移和 Kafka 集成任务在 `.github/workflows/ci.yml` 中运行。

## 文档

| 主题 | 文档 |
|---|---|
| 数据检查与 ALS 切分决策 | `docs/mind_data_inspection.md` |
| 汇总数据分析 | `docs/data_analysis_report.md` |
| 推荐指标 | `docs/metrics.md` |
| 机器可读的推荐证据 | `docs/metrics/mind_recommendation.json` |
| 搜索机制证据 | `docs/metrics/mind_intent_mechanism.json` |
| 搜索相关性评估 | `docs/search_relevance.md` |
| 机器可读的搜索证据 | `docs/metrics/mind_search_relevance.json` |
| 混合搜索面试深度解析 | `docs/search_hybrid_interview.md` |
| API 与事件契约 | `docs/api_contract.md` |
| 本地运维 | `docs/local_runbook.md` |
| 产品/HCI 演示 | `docs/hci_report.md` |
| 迁移计划 | `plan/mind_migration_plan_zh.md` |
