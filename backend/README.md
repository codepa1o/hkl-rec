# NewsIntentRec 后端

用于文章信息流、搜索、事件接入、画像状态、赞助内容投放、健康检查和可观测性的 FastAPI 逻辑单体应用。

- PostgreSQL 是唯一的在线事实来源，驱动使用 psycopg 3 连接池。
- SQLAlchemy Core metadata 是数据库结构定义，Alembic 负责版本化迁移。
- `PostgresRuntimeRepository` 将旧版 `answer`/`question` 表映射为公共文章模型。
- `sync_postgres`、`kafka_dual_write` 和 `kafka_async` 共享幂等事件与持久化 Outbox 语义。
- 旧 MySQL 连接仅存在于一次性的历史数据迁移工具中，不参与应用运行时读写。

主要 API 分组：账号、推荐、搜索、文章、事件、画像调试、健康检查与指标。

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
