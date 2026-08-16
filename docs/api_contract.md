# NewsIntentRec API 契约

公共内容标识统一为 MIND 原生字符串 `news_id`。内容字段使用 `title`、`abstract`、`url`、
`source_domain`、`category`、`subcategory` 和派生的 `categories`；运行时不提供旧内容 ID 兼容层。

## 主要路由

- `GET /feed`
- `POST /search`
- `GET /articles/{news_id}`
- `POST /event/track`
- `POST /event/recommendation_click`
- `POST /event/search_result_click`
- `GET /personas`
- `GET /debug/profile`
- `GET /livez`、`/readyz`、`/healthz`、`/metrics`

信息流与搜索项使用以下核心结构：

```json
{
  "news_id": "N123",
  "title": "Real MIND title",
  "abstract": "Real MIND abstract",
  "url": "https://example.com/news/N123",
  "source_domain": "example.com",
  "category": "news",
  "subcategory": "local",
  "categories": [{"topic_id": 1, "display_name": "news"}]
}
```

`GET /feed` 接受 `user_id`、`page_size`、`debug`、`request_id`、
`include_sponsored`、`experiment_arm`、可选不透明 `cursor`，以及仅用于评估的 `as_of_ts`。
`lgb_plus_als_plus_search_mmr` 是非默认自然信息流实验分组；赞助内容固定槽位混排仍是
`default` 分组的产品行为。

产品前端以每页 20 篇请求信息流。首个响应的 `next_cursor` 用于请求下一页，`has_more` 表示
当前会话是否仍有未展示新闻；服务端会排除该会话已经返回的 `news_id`。客户端必须为每一页
提供新的 `request_id`，用于幂等、曝光和点击归因；翻页失败可用同一个 `cursor` 重试。

```json
{
  "user_id": 42,
  "request_id": "feed-page-2",
  "items": [],
  "next_cursor": "opaque-next-page-token",
  "has_more": true
}
```

`GET /articles/{news_id}` 除核心新闻字段外返回解析后的 `title_entities` 和
`abstract_entities`。实体类型为 `person`、`organization`、`location` 或 `other`，并保留 MIND 类型码、
Wikidata ID、置信度和表面形式。前端只在详情页按人物、机构、地点分组展示，并优先按
Wikidata ID 去重。

`POST /search` 接受规范化 `query_key` 或英文 `query_text`。数值键以及精确类别/子类别别名
走确定性主题路径；其他自由文本使用 BM25、sentence-transformer/FAISS 和加权 RRF。
低置信度输入返回 422 `unresolved_query`；全目录搜索制品缺失、损坏、指纹不匹配或本地模型
不可用时返回 503 `search_index_not_ready`。

统一产品事件使用以下结构：

```json
{
  "event_id": "client-idempotency-key",
  "user_id": 42,
  "event_type": "feed_impression",
  "surface": "feed",
  "news_id": "N123",
  "request_id": "feed-request"
}
```

新闻事件必须包含 `news_id`；搜索结果点击还必须包含 `query_key`，`dwell` 事件必须包含有界的
`dwell_ms`。Kafka 用户事件和训练消息均使用模式版本 4，旧模式消息会被明确拒绝。

赞助卡片使用同一新闻契约，并增加带标签的 `sponsored` 对象。服务端会依据 PostgreSQL 中的
投放记录验证 `user_id`、`news_id` 和 delivery ID，不直接信任客户端归因字段。
