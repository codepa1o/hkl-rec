# NewsIntentRec API 契约

公共内容字段包括 `article_id`、`headline`、`abstract`、`source_domain` 和 `categories`。
MySQL 兼容模式仍使用 answer/question 表名，但 OpenAPI 不会暴露这些名称。

## 主要路由

- `GET /feed`
- `POST /search`
- `GET /articles/{article_id}`
- `POST /event/track`
- `POST /event/recommendation_click`
- `POST /event/search_result_click`
- `GET /profile`
- `POST /profile/reset`
- `GET /personas`
- `GET /debug/profile`
- `GET /livez`、`/readyz`、`/healthz`、`/metrics`

信息流与搜索项使用以下结构：

```json
{
  "article_id": 123,
  "headline": "Real MIND headline",
  "abstract": "Real MIND abstract",
  "source_domain": "msn.com",
  "categories": [{"topic_id": 1, "display_name": "news"}]
}
```

`GET /feed` 接受 `user_id`、`page_size`、`debug`、`request_id`、
`include_sponsored`、`experiment_arm`，以及仅用于评估的 `as_of_ts`。
`lgb_plus_als_plus_search_mmr` 是非默认自然信息流实验分组：它保留
`scores.final_score` 作为 LightGBM 相关性分数，只通过混合 ALS/主题 MMR 改变返回顺序。
赞助内容的固定槽位混排仍是 `default` 分组的产品行为。

`profile_v2` 是显式选择的画像实验分组，不会自动替换 `default`。它沿用默认分组的召回与
排序配置，仅把 V2 正向主题加入额外召回，并将候选文章命中的正负主题分数乘以
`NEWSREC_PROFILE_V2_BOOST` 后加到最终分数。调试分数增加可空字段
`scores.profile_v2_score`。V2 为空时顺序与原排序一致；V2 查询失败时服务会回滚到读取前的
数据库保存点、记录 `profile_v2_read_fallback_total`，并继续返回原排序结果。

## 正式用户画像

`GET /profile` 和 `POST /profile/reset` 始终要求有效登录会话，不接受 `user_id` 参数，
目标用户只由服务端会话确定。`GET /debug/profile?user_id=...` 保留用于受控研究和演示；
启用鉴权时仍执行本人/演示用户授权检查。

正式画像响应只返回结构化证据，解释文案由客户端本地生成：

```json
{
  "user_id": 7004,
  "profile_version": "v2",
  "status": "learning",
  "confidence": 0.632121,
  "evidence_count": 8,
  "short_term": {
    "interests": [{
      "topic_id": 12,
      "display_name": "technology",
      "score": 0.72,
      "positive_score": 0.9,
      "negative_score": 0.18,
      "positive_evidence_count": 4,
      "negative_evidence_count": 1,
      "signal_counts": {"recommendation_click": 2, "dwell": 2, "downvote": 1},
      "last_signal_type": "dwell",
      "last_event_ts": 1786852800
    }],
    "reduced_topics": []
  },
  "long_term": {"interests": [], "reduced_topics": []},
  "recent_clicked_news": [],
  "recent_queries": [],
  "last_updated_at": "2026-08-16T12:00:00Z"
}
```

`status` 取值为 `cold`、`learning` 或 `established`；`confidence` 范围为 0–1。
重置成功返回新的冷启动画像。重置保留 `user_event` 审计记录，并设置事件时间边界，确保
旧的 Kafka 重试或重建不会恢复重置前兴趣。本接口可能返回：

- 401：会话缺失或失效；
- 404 `PROFILE_NOT_INITIALIZED`：账号尚无 `user_profile` 行；
- 503 `PROFILE_SEED_UNAVAILABLE`：配置的系统冷启动种子不存在；
- 503 `repository_not_ready`：PostgreSQL 运行时不可用。

`POST /search` 接受规范化 `query_key` 或英文 `query_text`。
数值键以及精确的类别/子类别别名使用确定性主题路径；其他自由文本使用 BM25、
sentence-transformer/FAISS 检索和加权 RRF。系统只返回高置信度候选项，
不会用热门文章填满不足一页的搜索结果。低置信度输入返回 422 `unresolved_query`；
混合搜索制品缺失、损坏、过期或本地不可用时返回 503 `search_index_not_ready`。

搜索评分字段包括 `topic_match_score`、`bm25_score`、`dense_score`、
`hybrid_score` 和 `final_score`。调试输出包含检索模式、解析来源/置信度、
结果来源、匹配主题和模型制品标识。

统一产品事件使用以下结构：

```json
{
  "event_id": "client-idempotency-key",
  "user_id": 42,
  "event_type": "feed_impression",
  "surface": "feed",
  "article_id": 123,
  "request_id": "feed-request"
}
```

文章事件必须包含 `article_id`；搜索结果点击还必须包含 `query_key`，
`dwell` 事件必须包含有界的 `dwell_ms`。Kafka 用户和训练消息使用模式版本 3。
消费者保留内部模式 v2 迁移适配层，使已暂存的旧版内容 ID 消息可以被排空，
同时不改变幂等指纹。

赞助卡片使用相同的文章字段，并增加带标签的 `sponsored` 对象。
服务端会依据 MySQL 验证赞助内容 ID，而不会直接信任客户端提供的值。
