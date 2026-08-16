# NewsIntentRec 后端

用于文章信息流、搜索、事件接入、画像状态、赞助内容投放、健康检查和可观测性的 FastAPI 逻辑单体应用。

- PostgreSQL 是唯一的在线事实来源，驱动使用 psycopg 3 连接池。
- SQLAlchemy Core metadata 是数据库结构定义，Alembic 负责版本化迁移。
- `PostgresRuntimeRepository` 将旧版 `answer`/`question` 表映射为公共文章模型。
- `sync_postgres`、`kafka_dual_write` 和 `kafka_async` 共享幂等事件与持久化 Outbox 语义。
- 旧 MySQL 连接仅存在于一次性的历史数据迁移工具中，不参与应用运行时读写。

主要 API 分组：账号、推荐、搜索、文章、事件、正式画像、画像调试、健康检查与指标。

```bash
export NEWSREC_DATABASE_URL='postgresql+psycopg://newsrec:newsrec@127.0.0.1:5432/newsrec_demo'
export NEWSREC_AUTH_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
python -m alembic upgrade head
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

迁移历史 MySQL 数据：

```bash
export NEWSREC_MYSQL_SOURCE_URL='mysql+pymysql://root:root@127.0.0.1:3307/newsrec_demo'
python scripts/migrate_mysql_to_postgres.py
```

迁移器要求 PostgreSQL 已位于 Alembic head 且业务表为空；迁移在单一目标事务中执行，任一表复制或校验失败都会整体回滚。生产环境通过 HTTPS 运行时还需设置 `NEWSREC_AUTH_COOKIE_SECURE=1`。

完整技术栈说明请参阅 `docs/local_runbook.md`。

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

`POST /profile/reset` 在同一事务内恢复系统冷启动种子、清空 V1/V2 派生画像并记录重置边界，
但保留 `user_event` 审计事实。种子缺失时事务回滚并返回
`PROFILE_SEED_UNAVAILABLE`；用户画像未初始化时返回 `PROFILE_NOT_INITIALIZED`。
紧急回退只需设置 `NEWSREC_PROFILE_V2_ENABLED=0`：它会停止新投影，并使显式
`profile_v2` Feed 分组使用原排序；不要通过回退迁移删除画像表或历史事件。
