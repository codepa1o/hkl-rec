# NewsIntentRec 后端

用于文章信息流/搜索服务、事件接入、画像状态、赞助内容投放、健康检查和可观测性的
FastAPI 逻辑单体应用。

- MySQL 是在线事实来源。
- `MysqlRuntimeRepository` 仅将旧版 answer/question 表作为迁移兼容层；公共模型对外暴露文章/新闻字段。
- `sync_mysql`、`kafka_dual_write` 和 `kafka_async` 事件模式共享幂等事件标识和持久化 Outbox 语义。
- Kafka 用户/训练消息使用包含 `article_id` 的 v3 模式；消费者仍可排空已暂存的 v2 内容 ID 消息。
- `build/mind_models` 下的 LightGBM 和 ALS 制品是可选的，并会校验模式与指纹。
- `build/mind_search/demo` 下的混合搜索制品包含 BM25 语料数据、规范化 MiniLM 嵌入、FAISS 索引、模型修订号、哈希值，以及选定的拒绝/融合配置。

主要 API 分组：

- 推荐：`/feed`；
- 搜索：`/search`、`/search/suggestions`；
- 产品内容：`/personas`、`/articles/{article_id}`；
- 事件：`/event/track` 和点击端点；
- 调试：`/debug/profile`；
- 系统：`/livez`、`/readyz`、`/healthz`、`/metrics`。

```bash
export NEWSREC_DATABASE_URL='mysql+pymysql://root:root@127.0.0.1:3307/newsrec_demo'
python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

完整技术栈说明请参阅 `docs/local_runbook.md`。
