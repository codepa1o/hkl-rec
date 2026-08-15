# PostgreSQL 与 Alembic 迁移设计

## 目标

把 PostgreSQL 作为应用唯一运行时数据库，以 Alembic 管理全部表结构；保持现有表名、字段语义、主外键、唯一约束和历史主键不变，并将当前 MySQL 全量历史数据迁入 PostgreSQL。原 MySQL 在验收完成前只读保留，作为回滚依据。

## 技术选择

- PostgreSQL 16 Docker 容器作为本地目标库。
- psycopg 3 + `psycopg_pool.ConnectionPool` 作为同步 FastAPI Repository 的运行时驱动，使用 `dict_row` 保持现有字典行接口。
- SQLAlchemy 2 `MetaData` 定义数据库结构，Alembic 的 `target_metadata` 引用该对象；首个 revision 创建与现有 MySQL 逻辑等价的 PostgreSQL 表。
- PyMySQL 仅保留给一次性 MySQL 历史数据读取工具，不再参与应用运行时。

## 迁移边界

1. Alembic 在空 PostgreSQL 中执行 `upgrade head`，创建全部业务表和 `alembic_version`。
2. 停止 MySQL 写入后，迁移脚本按外键拓扑分批复制所有表，保留原始 ID、时间、JSON 和状态字段。
3. 导入在单个目标事务中执行；任一表失败则回滚 PostgreSQL，MySQL 不做任何写操作。
4. 校验每张表源/目标行数，并对按主键排序的规范化记录计算 SHA-256；任何不一致都返回非零退出码。
5. 校准 PostgreSQL 自增序列，使新写入从历史最大 ID 后继续。
6. 通过真实 PostgreSQL API、认证、事件和迁移测试后，应用连接串切换到 PostgreSQL。

## 方言适配

- `%s` 参数继续由 psycopg 支持。
- MySQL `ON DUPLICATE KEY UPDATE` 改为 PostgreSQL `ON CONFLICT ... DO UPDATE/NOTHING`。
- `UNIX_TIMESTAMP()` 改为 `EXTRACT(EPOCH FROM CURRENT_TIMESTAMP)::BIGINT`。
- `JSON_ARRAY()` 改为 PostgreSQL JSONB 字面量/参数。
- MySQL `ENUM` 用受 CHECK 约束的 `VARCHAR` 表示，避免 PostgreSQL enum 类型给未来 Alembic 变更增加额外生命周期管理。
- `ON UPDATE CURRENT_TIMESTAMP` 由写入 SQL 显式更新或 PostgreSQL trigger 保持既有语义。

## 本地与回滚

主 `docker-compose.yml` 启动 PostgreSQL。旧 MySQL compose 保存在迁移专用 compose 文件中。切换失败时应用只需恢复旧连接串；不销毁 PostgreSQL 或 MySQL 数据卷。

## 验收标准

- 空库执行 `alembic upgrade head` 成功，重复升级无变化，schema 与 SQLAlchemy metadata 一致。
- 所有 Repository 和认证路径使用 PostgreSQL，健康检查报告 `postgresql`。
- 历史迁移报告所有表行数和 SHA-256 一致，主键与关联关系不变。
- 真实 PostgreSQL 集成测试、后端非外部依赖测试、静态检查和前端回归全部通过。
