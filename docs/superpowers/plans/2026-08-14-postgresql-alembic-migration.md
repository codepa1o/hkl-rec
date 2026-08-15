# PostgreSQL + Alembic + 历史数据迁移实现计划

> 执行约束：测试先行；原 MySQL 只读；每个阶段完成后运行对应验证。

## Task 1：建立 PostgreSQL 连接契约

**Files:** `tests/test_postgres_connection.py`, `backend/app/repositories/connection.py`, `backend/app/config.py`, `backend/requirements.txt`

1. 先写 PostgreSQL URL、默认端口、连接池与事务行为测试并确认失败。
2. 实现 psycopg3 配置、字典行连接池和事务封装。
3. 将 MySQL 专属设置重命名为通用 PostgreSQL 设置，运行单元测试、Ruff、Mypy。

## Task 2：建立 SQLAlchemy metadata 和 Alembic 基线

**Files:** `tests/test_alembic_schema.py`, `backend/app/db/schema.py`, `alembic.ini`, `alembic/env.py`, `alembic/versions/20260814_0001_postgresql_baseline.py`

1. 先写 metadata 表集合、关键约束和 Alembic 配置测试并确认失败。
2. 定义全部现有表的 SQLAlchemy metadata。
3. 配置 Alembic `target_metadata` 与数据库 URL，创建可升级/降级基线 revision。
4. 在真实空 PostgreSQL 执行 upgrade、current、schema 对比和 downgrade/upgrade 往返测试。

## Task 3：把运行时 Repository 切换到 PostgreSQL

**Files:** `backend/app/repositories/postgres.py`, `backend/app/repositories/*_dao.py`, `backend/app/auth/repository.py`, `backend/app/events/*.py`, `backend/app/dependencies.py`, `backend/app/health.py`, `tests/test_*postgres*.py`

1. 先把现有集成契约改为 PostgreSQL，增加 MySQL 方言禁用测试并确认失败。
2. 替换连接池、Repository 类型名及依赖装配。
3. 将 upsert、时间和 JSON SQL 改成 PostgreSQL 方言。
4. 运行认证、feed、search、event、outbox、sponsored 的真实 PostgreSQL 测试。

## Task 4：实现历史数据迁移器

**Files:** `tests/test_mysql_to_postgres_migration.py`, `scripts/migrate_mysql_to_postgres.py`, `backend/app/db/migration.py`

1. 先写空源、非空目标、JSON、枚举、时间、自增序列、回滚和全表校验测试并确认失败。
2. 实现只读 MySQL 源、单事务 PostgreSQL 目标、按 metadata 外键拓扑的批量复制。
3. 实现逐表计数与规范化 SHA-256 校验、序列校准和 JSON 报告。
4. 使用本地现有 MySQL 与新 PostgreSQL 做真实全量迁移并保存报告。

## Task 5：Docker、脚本、CI 与文档切换

**Files:** `docker-compose.yml`, `docker-compose.mysql-legacy.yml`, `.env.example`, `.github/workflows/ci.yml`, `scripts/init_local.ps1`, `scripts/init_local.sh`, `scripts/smoke_local.py`, `README.md`, `backend/README.md`

1. 先增加 compose/config/CI 合同测试并确认失败。
2. 主 compose 改为 PostgreSQL 16；旧 MySQL compose 仅用于源库迁移。
3. 本地初始化先等待 PG、执行 `alembic upgrade head`、再导入 demo/启动 API。
4. CI 使用 PostgreSQL service，并增加 MySQL→PostgreSQL 迁移集成覆盖。
5. 文档写明备份、停写、升级、迁移、校验、切换和回滚命令。

## Task 6：全量验收

1. 运行 Alembic 空库往返、历史数据真实迁移、真实 PostgreSQL 后端集成测试。
2. 运行全部非 Kafka 测试、Ruff、Mypy、前端测试和构建。
3. 运行 `git diff --check`，复核没有运行时 MySQL 依赖和未迁移表。
4. 仅在上述新鲜证据全部通过后报告完成；不自动提交或删除旧库。
