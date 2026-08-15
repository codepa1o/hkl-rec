# MIND 新闻模型硬切换设计

日期：2026-08-15  
状态：Approved

## 1. 目标

将项目的在线新闻事实源从历史兼容模型 `question`、`answer`、`author`、
`question_topic`、`answer_topic` 和 `hot_answer_snapshot` 硬切换为严格对应
MIND `news.tsv` 的 `mind_news` 表，并完成数据库、导入、后端、事件契约、搜索、
推荐、前端、测试和文档的同步迁移。

完成后：

- PostgreSQL 中存在全部 65,238 条去重 MIND-small 新闻；
- 在线搜索索引覆盖全部 65,238 条新闻；
- Feed、搜索、详情、画像更新和事件均使用原始字符串 `news_id`（如 `N12345`）；
- MIND 历史请求和曝光继续保存在规范化 Parquet 中，不写入在线 `user_event`；
- 旧内容表和旧 `answer_id`/`question_id` 运行路径被彻底删除。

## 2. 数据边界

### 2.1 原始新闻事实

`mind_news` 的八个业务字段与 MIND `news.tsv` 一一对应：

| MIND 字段 | PostgreSQL 字段 | 类型 |
|---|---|---|
| News ID | `news_id` | `VARCHAR(32)` |
| Category | `category` | `TEXT` |
| SubCategory | `subcategory` | `TEXT` |
| Title | `title` | `TEXT` |
| Abstract | `abstract` | `TEXT` |
| URL | `url` | `TEXT` |
| Title Entities | `title_entities` | `JSONB` |
| Abstract Entities | `abstract_entities` | `JSONB` |

`news_id` 是主键并校验 `^N[0-9]+$`。两个实体字段必须为 JSON 数组。空摘要保留为空字符串，
不虚构内容。表中不混入点击数、曝光数、热度或内部整数 ID。

### 2.2 派生在线统计

`mind_news_stats` 与 `mind_news` 一对一，保存：

- `news_id`；
- `first_seen_ts`；
- `click_count`；
- `impression_count`；
- `hot_score = click_count * 10 + impression_count`；
- `normalized_fingerprint`。

统计仅从 `impressions_train.parquet` 聚合，禁止读取 dev 点击标签，以避免把验证结果泄漏到
在线排序特征。dev-only 新闻允许统计为零，但仍可搜索、查看并参与探索召回。

### 2.3 在线行为

`user_event`、`event_idempotency`、`sponsored_creative`、`sponsored_delivery` 和相关消息中的
内容外键统一从 `answer_id` 改为 `news_id`。在线行为表只记录产品运行期间产生的事件；
MIND 历史曝光与点击继续保存在：

- `requests_train.parquet`；
- `requests_dev.parquet`；
- `impressions_train.parquet`；
- `impressions_dev.parquet`。

## 3. PostgreSQL 模型

新增：

- `mind_news`；
- `mind_news_stats`；
- `mind_catalog_import`，记录规范化指纹、新闻行数、统计行数、导入时间和来源路径。

保留并改造：

- `app_user`、`user_account`、`auth_user_id_sequence`；
- `system_profile_seed`、`user_profile`；
- `query_topic_map`；
- `feed_request`；
- `user_event`、`event_idempotency`、`event_outbox`、`worker_heartbeat`；
- 赞助内容相关表，但将内容外键改为 `news_id`。

彻底删除：

- `question`；
- `answer`；
- `author`；
- `question_topic`；
- `answer_topic`；
- `hot_answer_snapshot`。

主题展示名称与画像权重继续需要稳定 topic ID，因此保留 `topic`。新闻的 category 与
subcategory 原文存放在 `mind_news`；需要 topic ID 的推荐路径通过规范化 `id_maps.json`
和确定性映射维护，不再把新闻事实拆散到旧兼容表。

## 4. 全量目录导入

新增 PostgreSQL 直连导入器 `scripts/import_mind_catalog.py`：

1. 读取 `build/mind_normalized/articles.parquet` 和 `normalization_manifest.json`；
2. 读取 `impressions_train.parquet`，按 `article_id` 聚合训练期曝光和点击；
3. 使用 `id_maps.json` 将内部整数 article ID 还原为原始 `news_id`；
4. 在 PostgreSQL 临时表中批量装载新闻、统计和主题映射；
5. 校验 65,238 个唯一 `news_id`、实体 JSON、外键和行数；
6. 在单个事务内 upsert 正式表并写入 `mind_catalog_import`；
7. 失败时整体回滚；重复执行保持幂等；
8. 不删除或重放在线用户事件。

导入器默认拒绝指纹与现有目录不一致的覆盖，只有显式 `--replace-catalog` 才允许版本替换。
本次硬切换迁移会显式使用该参数，因为用户已授权删除旧内容模型并导入当前完整数据集。

## 5. 标识与契约

所有产品边界统一使用 `news_id: str`：

- REST：`GET /articles/{news_id}`，例如 `/articles/N12345`；
- Feed/Search 响应：`news_id`；
- 点击、曝光、停留、赞踩、分享事件：`news_id`；
- Kafka/Outbox 消息：`news_id`；
- 前端路由和 TypeScript 类型：`newsId`。

ALS、LightGBM 和 FAISS 允许继续使用紧凑整数索引，但模型 artifact 必须携带完整且带指纹的
`news_id <-> internal_id` 映射。映射只存在于模型边界，不能成为数据库新闻主键。

旧 `article_id`、`answer_id` 和 `question_id` 不提供长期双写。数据库迁移、API、事件和前端
在同一发布中硬切换。

## 6. 搜索

使用现有 `scripts/build_search_index.py --corpus full` 从 `articles.parquet` 构建：

- `documents.jsonl`；
- `article_id_map.json`（迁移后改为 `news_id_map.json`）；
- `dense.faiss`；
- `metadata.json`，其中 `document_count=65238`。

在线设置切换为 `build/mind_search/full`。配置新增显式搜索源指纹覆盖项，使 readiness 校验
规范化 manifest 指纹，而不是 demo-world 指纹。BM25/FAISS 命中后直接用 `news_id` 批量查询
`mind_news`，不得因旧 `answer` 表缺行而过滤结果。

## 7. 推荐

推荐候选使用三个来源：

1. 用户 category/subcategory 权重召回；
2. ALS 全量目录召回；
3. 全量目录探索召回，为低热度和 dev-only 新闻提供有界曝光机会。

排序特征从 `mind_news_stats`、用户画像和搜索信号读取。探索通道只占小比例，并使用稳定、
可测试的分桶选择，避免 `ORDER BY RANDOM()` 全表扫描。所有候选在返回前批量读取
`mind_news`，不存在的 `news_id` 必须记录为 artifact/目录不一致错误。

“覆盖全部文章”定义为：每条 `mind_news` 都能被搜索、详情访问，并在至少一个合法主题或探索
召回路径中具备被选中的可能；不承诺每次请求展示整个目录。

## 8. 前端

前端同步修改：

- Feed 卡片、搜索结果、详情页和事件请求改用 `newsId`；
- 详情路由支持 `/articles/N12345`；
- 显示 `title`、`abstract`、`source_domain`（由 URL 解析）、category 和 subcategory；
- 移除残余 answer/question 命名。

## 9. 迁移顺序

1. 增加新表和新字段，提供全量导入器；
2. 导入并校验完整 MIND-small 目录；
3. 构建并校验 full 搜索索引；
4. 切换后端查询、推荐、事件和 API；
5. 切换前端；
6. 迁移保留的 demo 用户和画像；
7. 删除旧内容外键与旧内容表；
8. 运行完整质量门禁和 PostgreSQL 集成测试；
9. 在目标本地 PostgreSQL 执行 Alembic 和全量目录导入。

数据库迁移必须在单个受控流程内执行。破坏性 DDL 前核对目标 URL、主机、端口和数据库名，
并只允许 `newsrec_demo` 或显式测试库。

## 10. 验收标准

- `mind_news` 恰有 65,238 行且八字段与 Parquet/原始 MIND 一致；
- `mind_news_stats` 对每篇新闻恰有一行；
- 两个 JSONB 实体字段全部是数组；
- `question`、`answer`、`author`、`question_topic`、`answer_topic`、
  `hot_answer_snapshot` 不再存在；
- 全量搜索 artifact 的 `document_count` 为 65,238；
- 随机抽取的 train、dev-only 和非 demo 新闻均可通过详情接口访问；
- 搜索能够返回非 demo 新闻；
- Feed 能返回非 demo 新闻且探索通道受限、确定性可测；
- API、Kafka、Outbox、前端均不再暴露 `answer_id`/`question_id`；
- 重复导入不产生重复行，导入前后在线 `user_event` 行数不变；
- Ruff、Mypy、Pytest、PostgreSQL 集成测试、前端测试和构建全部通过。

## 11. 回滚边界

这是经用户批准的硬切换，不保留旧内容表兼容视图。代码回滚必须与数据库恢复一起进行；
不支持新代码连接旧 schema 或旧代码连接新 schema。目录导入失败在事务内回滚，DDL 迁移失败
由 Alembic 事务回滚。目标数据库执行前保留 Docker volume 或数据库备份是运维前置条件。
