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
- 可解释的短/长期主题画像、点踩/可见停留反馈、置信度与一键冷启动重置；
- Argon2 密码哈希、HttpOnly Cookie 会话、登录注册和受保护前端路由；
- MIND-small train/dev 全目录直接落 PostgreSQL，在线推荐与搜索覆盖全部唯一新闻。

## 当前证据

规范化数据指纹：
`a0144602f29ee9e07f91d4a67eca0cda5e2ee016f910a62a4a75aeae072f2e9d`。

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
| 旧版词法搜索 | 0.0058 | 0.0043 | 0.0075 | 0.0 |
| BM25 | 0.4274 | 0.4415 | 0.4887 | 1.0 |
| 稠密检索 | **0.6233** | **0.5944** | **0.6216** | 1.0 |
| 混合检索 | 0.5548 | 0.5756 | 0.6040 | 1.0 |

混合检索通过了冻结的上线门槛，并在拼写/噪声查询上表现最好，因此被设为默认方案。
稠密检索是整体留出评估中最强的分组；项目保留了这一对混合检索不利的结果，而未将其隐藏。

现有信息流本地回环测量的 p50/p95 为 9.47/14.18 ms；该结果仅是本地测量值，
不代表生产环境容量。

## 数据准备

请阅读 [Microsoft Research 许可条款](https://github.com/msnews/MIND/blob/master/MSR%20License_Data.pdf)。
MIND 官方页面当前会将下载请求转至需要授权的 Hugging Face 访问入口。
下载器要求明确接受许可，并支持该来源或显式选定的公开原始文件镜像：

```bash
python scripts/download_mind.py --variant small --split all --accept-license --source huyva
python scripts/inspect_mind.py --variant small
python scripts/normalize_mind.py
python -m alembic upgrade head
python scripts/import_mind_catalog.py \
  --normalized-root build/mind_normalized \
  --replace-catalog
python scripts/build_search_index.py \
  --input-dir build/mind_normalized \
  --output-dir build/mind_search/full \
  --model-revision 1110a243fdf4706b3f48f1d95db1a4f5529b4d41 \
  --config evaluation/search_relevance/selected_config.json
python scripts/calibrate_search_relevance.py
python scripts/eval_search_relevance.py \
  --config evaluation/search_relevance/selected_config.json
python scripts/train_eval_mind.py
```

原始 MIND 文件、规范化 Parquet、全量搜索索引和模型二进制文件均保留在本地，不提交到仓库。
`mind_news` 严格保存 `news.tsv` 的八个原始字段；训练期统计和导入证明分别保存在
`mind_news_stats` 与 `mind_catalog_import`，不会污染新闻源字段。`topic.topic_key` 保存稳定的
`category:<name>` / `subcategory:<category>/<name>` 身份，`mind_news_topic` 为每篇新闻保存恰好
两条精确关联，避免同名子分类串联。

产品首页首批展示 20 篇新闻，并在接近页面底部时通过不透明游标继续加载；一个浏览会话内
不会重复展示相同 `news_id`。MIND 的标题实体和摘要实体由详情接口解析，仅在文章详情页按
人物、机构、地点等分组展示。八个源字段与具体页面渲染位置见
[`docs/mind_news_field_rendering.md`](docs/mind_news_field_rendering.md)。

## 本地初始化

```bash
python -m pip install -r backend/requirements-dev.txt
BUILD_SEARCH_INDEX=1 scripts/init_local.sh
```

Windows PowerShell 使用 `./scripts/init_local.ps1 -BuildSearchIndex`。

`docker-compose.yml` 默认启动 PostgreSQL 16，应用启动前必须把 Alembic 升级到最新版本：

```bash
docker compose up -d --wait postgres
python -m alembic upgrade head
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

默认数据库为 `newsrec_demo`，规范化目录为 `build/mind_normalized`，全量搜索索引目录为
`build/mind_search/full`。公共 API 使用 MIND `news_id`，文章路由为 `/articles/{news_id}`。

## 用户画像 V2 MVP

画像 V2 以 PostgreSQL 为事实源，使用推荐点击、搜索结果点击、点赞、点踩和可见停留时间
生成带时间衰减的短期/长期主题证据；本期不引入语义向量。正式产品接口为登录态专用的
`GET /profile` 与 `POST /profile/reset`，用户 ID 只从 HttpOnly Cookie 会话确定。
研究与演示兼容接口 `GET /debug/profile?user_id=...` 保持不变。

V2 默认关闭，且不会改变默认 Feed 排序。迁移数据库后，可按以下顺序灰度：

```bash
python -m alembic upgrade head
NEWSREC_PROFILE_V2_ENABLED=1 python scripts/rebuild_profile_v2.py --all --dry-run
NEWSREC_PROFILE_V2_ENABLED=1 python scripts/rebuild_profile_v2.py --all
```

通过 `GET /feed?...&experiment_arm=profile_v2` 显式进入实验分组；读取 V2 失败时会在数据库
保存点回滚并继续使用原排序。将 `NEWSREC_PROFILE_V2_ENABLED=0` 即可停止新投影并让该实验
分组退化为原排序，`default` 分组始终不受影响。重置画像只清理派生投影并恢复冷启动种子，
不会删除历史事件；重置时间边界也会阻止旧事件在消费重试或重建时重新写回画像。

MIND 只提供曝光与点击行为，不提供真实搜索、点踩或停留标签。因此现有离线数据只能验证
画像投影、衰减、降级和重建机制，不能证明点踩/停留带来线上 CTR 或因果收益；
`profile_v2` 必须在获得独立离线与在线实验依据后才可考虑升级为默认分组。

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

PostgreSQL、MIND 目录导入和 Kafka 集成任务在 `.github/workflows/ci.yml` 中运行。

## MIND / 实时新闻双空间

产品可以在固定的 MIND 数据集与持续更新的 Live 新闻之间切换。两个空间共用登录账号和
Persona 入口，但画像、事件、搜索历史、分页游标与重置状态均按 `source_space` 隔离；关闭
Live 展示或采集器不会删除已导入的新闻与画像。GDELT GAL 仍只负责发现标题、摘要、图片 URL、
发布者、时间与原文链接；独立正文 Worker 仅对来源策略明确允许的文章，通过官方 API、全文
RSS 或白名单 HTML 抽取异步补全纯文本正文。没有权限或获取失败时详情页稳定降级为摘要和
原文链接。Live 不复用 MIND 的主题、向量、模型、热度或赞助内容。

首次启动前执行迁移，并先用一次性模式验证采集链路：

```bash
python -m alembic upgrade head
python scripts/run_live_news_collector.py --once
python scripts/run_live_news_collector.py --poll-interval-seconds 60
python scripts/run_live_news_content_worker.py --once
python scripts/run_live_news_content_worker.py --poll-interval-seconds 5
```

相关开关为 `NEWSREC_LIVE_NEWS_ENABLED`、`NEWSREC_LIVE_NEWS_COLLECTOR_ENABLED` 与
`NEWSREC_LIVE_CONTENT_WORKER_ENABLED`。Guardian 官方正文接口还需要
`NEWSREC_GUARDIAN_API_KEY`；公共 `test` key 仅用于本地验证，持续运行应使用开发者 key。发布者白名单位于
`config/live_news_sources.json`，只接受精确域名边界及配置的中文/英文内容；修改后应先运行
规范化、Provider 和 Worker 测试。正文只以安全文本段落渲染，不执行发布者 HTML；远程图片
加载失败时前端隐藏图片并保留文字卡片。原文链接可定时巡检：

```bash
python scripts/check_gdelt_connectivity.py --timeout-seconds 10
python scripts/check_live_news_links.py --limit 100 --timeout-seconds 10
```

连续三次无法访问的原文会被标记为 `inactive`，历史行不会物理删除。Live 首版 Feed 仅按
新鲜度、元数据质量和来源多样性排序；虽然行为被写入独立 Live 画像，但当前不宣称已实现
个性化排序。MIND 的导入、训练、搜索工件与离线评估继续只读取 MIND 数据。

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
