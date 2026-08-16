# NewsIntentRec 后端

用于 MIND 新闻信息流、全目录搜索、事件接入、画像状态、赞助内容投放、健康检查和可观测性的 FastAPI 逻辑单体应用。

- PostgreSQL 是唯一在线事实来源，运行时使用 psycopg 3 连接池。
- `mind_news` 严格对应 MIND `news.tsv` 的八个字段，主键为原生字符串 `news_id`。
- `mind_news_stats` 保存训练期曝光/点击统计，`mind_catalog_import` 保存导入指纹与行数证明。
- `mind_news_topic` 保存每篇新闻严格两条 category/subcategory 关联；`topic_key` 使用父分类限定
  子分类身份，不按显示名猜测关联。
- SQLAlchemy Core metadata 定义数据库结构，Alembic 管理版本化迁移。
- `sync_postgres`、`kafka_dual_write` 和 `kafka_async` 共享幂等事件与持久化 Outbox 语义。

主要 API 分组：账号、推荐、搜索、新闻详情、事件、正式画像、画像调试、健康检查与指标。
`GET /feed` 支持不透明 `cursor`，响应包含 `next_cursor` 和 `has_more`；同一分页会话会排除
已返回新闻。`GET /articles/{news_id}` 返回解析后的标题实体与摘要实体。

```bash
export NEWSREC_DATABASE_URL='postgresql+psycopg://newsrec:newsrec@127.0.0.1:5432/newsrec_demo'
export NEWSREC_AUTH_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
export NEWSREC_MIND_NORMALIZED_DIR=build/mind_normalized
export NEWSREC_SEARCH_INDEX_DIR=build/mind_search/full
python -m alembic upgrade head
python scripts/import_mind_catalog.py --normalized-root build/mind_normalized --replace-catalog
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

生产环境通过 HTTPS 运行时还需设置 `NEWSREC_AUTH_COOKIE_SECURE=1`。完整运行说明请参阅 `docs/local_runbook.md`。

## Profile V2 运维

先执行 Alembic 迁移，再开启画像投影。五个配置项及默认值如下：

```text
NEWSREC_PROFILE_V2_ENABLED=0
NEWSREC_PROFILE_V2_SHORT_HALF_LIFE_SECONDS=21600
NEWSREC_PROFILE_V2_LONG_HALF_LIFE_SECONDS=2592000
NEWSREC_PROFILE_V2_LONG_TERM_FACTOR=0.25
NEWSREC_PROFILE_V2_BOOST=0.10
```

重建命令复用线上信号和投影函数，并按 `(user_id, event_ts, event_id)` 稳定回放；实时执行时
每个用户使用独立事务，一个用户失败不会回滚其他用户。先检查数量再执行：

```bash
python scripts/rebuild_profile_v2.py --user-id 7004 --dry-run
python scripts/rebuild_profile_v2.py --user-id 7004
python scripts/rebuild_profile_v2.py --all --dry-run
python scripts/rebuild_profile_v2.py --all
```

`POST /profile/reset` 在同一事务内恢复系统冷启动种子、清空 V1/V2 派生画像并记录时间与事实事件 ID 双重边界，
但保留 `user_event` 审计事实。种子缺失时事务回滚并返回
`PROFILE_SEED_UNAVAILABLE`；用户画像未初始化时返回 `PROFILE_NOT_INITIALIZED`。
紧急回退只需设置 `NEWSREC_PROFILE_V2_ENABLED=0`：它会停止新投影，并使显式
`profile_v2` Feed 分组使用原排序；不要通过回退迁移删除画像表或历史事件。
