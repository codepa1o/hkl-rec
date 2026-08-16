# 用户画像 V2 可上线 MVP 设计

## 目标

在不改变默认推荐分组的前提下，把当前单层、仅正向累积的主题画像升级为可上线的 V2 画像：分别表达短期兴趣和长期兴趣，吸收点踩与有效停留反馈，给出画像置信度和结构化解释，并为登录用户提供正式画像接口和一键恢复冷启动能力。

V2 通过独立的 `profile_v2` 推荐实验分组参与召回和重排。现有 `user_profile`、`GET /debug/profile?user_id=` 和默认推荐分组保持兼容，指标通过后再由人工决定是否提升为默认。

## 非目标

- 不引入 pgvector 或任何语义用户向量。
- 不引入 Feast、RecBole、Recommenders 或新的模型训练平台。
- 不重新训练或修改当前 LightGBM 特征顺序。
- 不提供逐主题手工增删或权重编辑。
- 重置画像不删除 `user_event`、训练消息或其他审计历史。
- 不依据 MIND 中不存在的真实点踩、停留日志宣称线上收益。

## 架构决策

采用“行为事实 + 双投影”架构：

- `user_event` 是不可变的行为事实记录。
- `user_profile` 是 V1 兼容投影，继续服务旧调试接口和默认推荐分组。
- 新表 `user_topic_profile` 是 V2 关系型实时投影，每个用户—主题一行。
- `ProfileEventApplier` 在同一个数据库事务中完成事件认领、事件落库、V1 更新和 V2 更新。
- 纯计算模块负责事件强度、半衰期衰减、有效分数和置信度；DAO 只负责读取、锁定和 UPSERT。
- `ProfileService` 负责正式画像查询与重置用例，路由层只处理会话身份和 HTTP 映射。

启用 V2 后，V2 写入失败会令整条事件事务回滚并进入现有重试/DLQ 流程。这样不会产生“V1 已更新而 V2 未更新”的分裂画像。关闭 `profile_v2_enabled` 时消费者完全跳过 V2 写入。

## 数据模型

新增 `user_topic_profile`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `user_id` | `BIGINT` | 用户 ID，联合主键和外键 |
| `topic_id` | `BIGINT` | 主题 ID，联合主键和外键 |
| `short_positive_score` | `DOUBLE PRECISION` | 已物化到 `last_event_ts` 的短期正向分 |
| `short_negative_score` | `DOUBLE PRECISION` | 已物化到 `last_event_ts` 的短期负向分 |
| `long_positive_score` | `DOUBLE PRECISION` | 已物化到 `last_event_ts` 的长期正向分 |
| `long_negative_score` | `DOUBLE PRECISION` | 已物化到 `last_event_ts` 的长期负向分 |
| `positive_evidence_count` | `INTEGER` | 正向主题证据次数 |
| `negative_evidence_count` | `INTEGER` | 负向主题证据次数 |
| `evidence_counts_json` | `JSONB` | 按事件类型累计的主题证据次数 |
| `last_signal_type` | `VARCHAR(32)` | 最近一次改变该主题的事件类型 |
| `last_event_ts` | `BIGINT` | 最近一次已投影事件时间 |
| `updated_at` | `TIMESTAMPTZ` | 数据库更新时间 |

联合主键为 `(user_id, topic_id)`；增加按 `user_id` 查询的索引。分数列非空且默认 `0`，计数列非空且默认 `0`。

在 `user_profile` 增加：

- `profile_v2_evidence_count INTEGER NOT NULL DEFAULT 0`
- `profile_v2_last_event_ts BIGINT NULL`
- `profile_reset_before_ts BIGINT NULL`
- `profile_reset_before_event_id BIGINT NULL`：记录重置事务可见的最大事实事件 ID，供重建精确排除同秒内的重置前事件。
- `profile_v2_updated_at TIMESTAMPTZ NULL`

这些字段只保存用户级投影状态，不改变现有 V1 字段含义。

## 衰减与信号规则

存储的分数以对应行的 `last_event_ts` 为时间基准。更新和读取都使用相同半衰期公式：

```text
decayed_score = score * 2 ^ (-elapsed_seconds / half_life_seconds)
```

默认短期半衰期为 6 小时，长期半衰期为 30 天。每个事件对长期层的增量是短期层增量的 25%。所有常量进入 `Settings` 并支持环境变量覆盖。

事件强度：

| 事件 | 短期信号 |
|---|---:|
| `recommendation_click` | `+1.00` |
| `search_result_click` | `+1.25` |
| `upvote` | `+2.00` |
| `downvote` | `-2.00` |
| `dwell` 小于 10 秒 | `0` |
| `dwell` 10–30 秒 | `+0.25` |
| `dwell` 30–120 秒 | `+0.50` |
| `dwell` 超过 120 秒 | `+0.75` |

`feed_impression`、`detail_view`、`share` 和未确认的搜索只落事件，不改变 V2。

正向信号增加 positive 分量，负向信号增加 negative 分量；两个分量独立衰减。有效净分为：

```text
short_net = short_positive_score - short_negative_score
long_net  = long_positive_score - long_negative_score
```

普通文章事件使用文章主题。`search_result_click` 对文章主题使用完整强度，对查询独有主题使用 50% 强度；文章与查询重合的主题只计一次完整强度。

低于 10 秒的停留不增加 `profile_v2_evidence_count`。其余有效 V2 事件每条只增加一次用户级证据数，即使文章关联多个主题；主题级计数按实际受影响主题分别增加。

## 置信度与状态

置信度只依赖有效画像事件数，避免按文章主题数量重复计数：

```text
confidence = 1 - exp(-profile_v2_evidence_count / 8)
```

状态映射：

- `confidence < 0.25`：`cold`
- `0.25 <= confidence < 0.75`：`learning`
- `confidence >= 0.75`：`established`

API 和推荐读取时会把存储分数衰减到请求时间。有效绝对净分不超过 `0.01` 的主题不进入返回结果或推荐计算；每层最多返回 10 个正向主题和 10 个负向主题。

## 顺序、一致性与幂等

- 继续使用现有 `claim_event_id` 保证重复事件不重复更新。
- Kafka 按用户分区仍是正常顺序保证。
- `event_ts < profile_reset_before_ts` 的晚到事件保留审计和训练用途，但不改变 V1/V2 当前画像。重置和在线投影都锁定同一用户行，因此同秒事件以锁的先后顺序确定因果边界；离线重建再用 `profile_reset_before_event_id` 排除同秒内的重置前事实。
- 比某个主题 `last_event_ts` 更旧的乱序事件不改变该主题投影，并增加晚到事件指标。
- 同一事件的用户级证据数只有在至少一个主题成功投影时才增加一次。
- 画像查询不在读取时写回衰减结果，避免 GET 引起更新；下一个有效事件到达时再物化衰减后的新值。

## 正式 API

新增：

```http
GET /profile
POST /profile/reset
```

两个接口均强制要求有效登录会话，不接受 `user_id` 参数。`GET /debug/profile?user_id=` 保持现有路径和响应契约。

`GET /profile` 返回：

```text
user_id
profile_version = "v2"
status
confidence
evidence_count
short_term.interests[]
short_term.reduced_topics[]
long_term.interests[]
long_term.reduced_topics[]
recent_clicked_news[]
recent_queries[]
last_updated_at
```

每个主题项包含：

```text
topic_id
display_name
score
positive_score
negative_score
positive_evidence_count
negative_evidence_count
signal_counts
last_signal_type
last_event_ts
```

后端返回结构化事件代码和次数，不返回固化的中文解释句。前端根据事件代码生成“近期多次阅读”“你曾点踩此类内容”等展示文案。

画像行不存在时返回带 `PROFILE_NOT_INITIALIZED` 错误码的 404。数据库不可用返回 503，不伪造 V1 或冷启动响应。

## 画像重置

`POST /profile/reset` 在单个事务中：

1. 锁定当前登录用户的 `user_profile`。
2. 读取该用户配置的 `system_profile_seed`；种子不存在则回滚并返回 503。
3. 用种子恢复 V1 `topic_weights_json`、近期点击、近期查询和 `behavior_score`。
4. 删除该用户全部 `user_topic_profile` 行。
5. 将 V2 证据数归零，并清空 V2 最近事件状态。
6. 把服务器当前时间写入 `profile_reset_before_ts`，并把事务当前可见的最大 `user_event.event_id` 写入 `profile_reset_before_event_id`。
7. 提交后返回新的冷启动 V2 画像。

重置不删除 `user_event`、`event_idempotency`、训练消息、Feed 请求或赞助归因。它是“停止使用既有行为形成当前画像”，不是账户数据删除接口。

## `profile_v2` 推荐实验分组

新增 `profile_v2` 实验分组，不改变 `default` 行为。V2 分组保留现有 V1 主题、查询、ALS、探索和热度召回，并额外加入 V2 合并净分为正的 Top-10 主题召回。负向主题不打开召回通道。

每个主题的实验分为：

```text
combined_topic_score =
    0.70 * tanh(short_net)
  + 0.30 * tanh(long_net)
```

文章 V2 分数是文章全部主题 `combined_topic_score` 之和，最终分为：

```text
final_score = existing_final_score + profile_v2_boost * profile_v2_score
```

`profile_v2_boost` 默认 `0.10` 并可配置。Feed Debug 响应增加可选 `profile_v2_score`，现有分数字段保持兼容。

用户没有有效 V2 主题时，`profile_v2` 必须退化为默认分组结果。V2 读取包在数据库 SAVEPOINT 中；查询 V2 表失败时回滚到 SAVEPOINT、记录回退指标并继续使用 V1 默认排序，不让已经中止的 PostgreSQL 事务继续执行。数据库连接本身不可用时仍按现有 Feed 错误处理返回服务错误。

## 前端设计

新增正式 `ProfilePanel`：

- 展示画像状态和置信度，不再把原始 `behavior_score` 当作画像成熟度。
- 分别展示“近期兴趣”和“长期兴趣”，每层默认 Top 5，可展开至 Top 10。
- 净负向主题显示在“减少推荐”区域。
- 证据说明由 `signal_counts` 和 `last_signal_type` 本地化生成。
- 重置按钮需要二次确认，并具有提交中、成功和失败状态。
- 重置成功后刷新画像和信息流。

当前登录用户使用 `ProfilePanel` 和正式 `/profile`。研究模式切换到其他 Demo Persona 时，继续使用原有 `ProfileDebugPanel` 和 `/debug/profile?user_id=`，防止右侧画像与信息流用户不一致。

文章详情页统计页面实际可见时间。标签页隐藏期间暂停累计；路由卸载或 `pagehide` 时使用稳定 `event_id` 发送至多一次 `dwell` 事件。发送失败不阻塞离开页面，也不重复弹出全局错误。

## 重建工具

新增可重复运行的 `scripts/rebuild_profile_v2.py`：

- 支持指定 `--user-id` 或 `--all`，两者必须二选一。
- 支持 `--dry-run` 输出待处理用户数、事件数和预计主题行数。
- 按用户、`event_ts`、稳定事件 ID 顺序重放 `user_event`。
- 在事务中删除目标 V2 行并重新投影，失败时回滚该用户。
- 复用在线消费者相同的信号和衰减纯函数，不维护第二套公式。
- 在用户行锁内读取重置边界；按 `profile_reset_before_ts` 与 `profile_reset_before_event_id` 联合过滤，不重放重置前事件。

数据库迁移不从 V1 JSONB 猜测证据，也不自动长事务回放历史。没有可重放事件的用户从冷 V2 开始，V1 推荐不受影响。

## 可观测性与错误处理

新增指标：

- `profile_v2_projection_updates_total{event_type}`
- `profile_v2_late_events_total{reason}`
- `profile_v2_read_fallback_total`
- `profile_v2_reset_total{status}`
- `profile_v2_projection_seconds`

消费者 V2 错误沿用当前重试、DLQ 和 heartbeat 报错机制。正式画像读取失败按现有 API 错误响应规范返回；前端保留现有内容并显示局部重试状态。

## 测试与验收

后端测试覆盖：

- 半衰期边界、正负独立衰减、净分、停留区间、置信度和乱序事件。
- 主题 UPSERT、用户级证据只计一次、锁与事务回滚。
- 事件重复、晚到、重置截止时间、Kafka 重试和 DLQ。
- 正式接口登录隔离、旧调试接口兼容、重置成功与种子缺失。
- V2 正向召回、负向降权、空画像退化和读取失败回退。
- 重建工具 dry-run、重复运行一致性、按用户回滚和重置截止时间。
- Alembic upgrade/downgrade 以及当前全套 Python、PostgreSQL 和 Kafka 测试。

前端测试覆盖：

- 短期、长期、减少推荐和置信度展示。
- 证据代码本地化、Top-5 展开和空画像状态。
- 重置确认、提交状态、失败恢复和成功后刷新。
- 当前用户使用正式接口，其他 Demo Persona 使用调试接口。
- 可见停留计时、隐藏暂停、稳定事件 ID 和重复发送保护。

离线与性能门槛：

- `profile_v2` 相对默认分组的 Recall@10、NDCG@10、MRR 任一绝对下降不超过 `0.005`。
- 本地 `profile_v2` Feed p95 相对默认分组增加不超过 5 ms，且总 p95 不超过 25 ms。
- MIND 不包含真实点踩和停留日志；相应测试和评估只证明机制正确，不作为线上收益证据。

指标通过后仍由人工修改默认实验分组，不自动晋升。

## 发布与回滚

发布顺序：先执行兼容性数据库迁移，再部署支持但默认关闭 V2 的后端，随后运行按需重建，最后开启 `profile_v2_enabled` 并仅通过显式实验分组访问。

关闭 `profile_v2_enabled` 即停止新投影；默认 Feed 和旧调试接口不受影响。回滚应用版本前先关闭开关。数据库新增表和列可以保留到后续维护窗口，不要求紧急 downgrade。
