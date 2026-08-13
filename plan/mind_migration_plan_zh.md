# MIND 数据集完整迁移计划

状态：**Completed (2026-07-21)**

目标项目名（工作名）：**NewsIntentRec**

数据源：公开的 **Microsoft News Dataset (MIND)**。该项目是个人工程项目，
不代表 Microsoft 官方产品，也不使用实习期间获得的内部数据、代码或访问权限。

官方资料：

- [MIND 官方主页](https://msnews.github.io/)
- [Azure Open Datasets 数据说明](https://learn.microsoft.com/en-us/azure/open-datasets/dataset-microsoft-news)
- [Microsoft Research License Terms](https://github.com/msnews/MIND/blob/master/MSR%20License_Data.pdf)

---

## 1. 最终目标

将当前基于 ZhihuRec 的内容社区推荐系统，完整替换为基于公开 MIND 数据集的
英文新闻推荐系统，同时保留并加强以下工程主线：

1. 真实 impression-aware 推荐训练与离线评测；
2. 多路召回、ALS/FAISS、LightGBM 排序和 hot/fresh fallback；
3. 用户点击、搜索和反馈驱动的在线画像更新；
4. MySQL、Outbox、Kafka、幂等消费和可观测性；
5. React 新闻 Feed、搜索、解释和多 persona 演示；
6. 一套不夸大结果、可用于简历和面试讲述的证据链。

迁移完成后，仓库不再依赖 ZhihuRec 原始文件，也不再把 ZhihuRec 指标作为当前结果。
历史实现可以从 Git 历史中查看，但当前 README、运行路径、数据报告和指标必须全部以
MIND 为准。

---

## 2. 核心决策

### 2.1 使用 MIND-small 作为默认开发数据

- 默认 bootstrap、CI fixture 和本地演示使用 MIND-small；
- MIND-large 作为可选的扩展实验，不作为开发和 CI 前置条件；
- raw zip、解压后的 TSV 和生成的大型模型文件不提交到 Git；
- 下载脚本必须要求用户显式确认已阅读研究许可，不能静默下载。

### 2.2 真实推荐证据与搜索机制证据分开

MIND 提供真实的新闻曝光、点击和点击历史，但**不提供用户搜索日志**。

因此：

- 推荐训练和 Recall/NDCG/AUC 评测只使用 MIND 的真实曝光与点击；
- 产品 Demo 中的搜索 query 来自本地用户真实输入；
- 离线搜索实验只能称为 `intent injection` 或机制验证；
- 不得声称 MIND 证明了“搜索提升 CTR”或“搜索导致推荐效果提升”；
- 原有 ZhihuRec Search Carryover 指标不迁移为 MIND 当前指标。

### 2.3 先保持内部兼容，再清理产品语义

为控制风险，第一阶段保留 MySQL 内部的 `answer`、`question`、`answer_id` 等兼容字段，
通过 MIND adapter 将新闻映射到现有 canonical import pack。

但是所有产品可见层必须改成新闻语义：

- `article_id`
- `headline`
- `abstract`
- `source_domain`
- `category`
- `subcategory`

后端 SQL 可以通过 alias 将内部字段映射为产品字段。是否重命名所有数据库表属于低收益、
高风险清理，不作为数据替换的阻塞项；README 必须明确这是迁移兼容层，而不是业务建模结论。

### 2.4 项目身份保持诚实

推荐表达：

> 基于公开 Microsoft MIND 数据集构建了个性化新闻推荐系统。

可以说明选择 MIND 与自己在 Microsoft 实习期间对推荐系统产生兴趣有关，但不得暗示：

- 项目是 Microsoft 实习交付；
- 使用了 Microsoft 内部日志、代码、模型或基础设施；
- Microsoft 对项目进行了背书；
- 数据来自本人实习团队。

---

## 3. 当前架构与可复用边界

当前最重要的可复用边界是：

```text
raw dataset
  -> demo-world builder
  -> canonical JSON/JSONL import pack
  -> MySQL
  -> repository/service/API
  -> frontend + event feedback
  -> model training/evaluation
```

`scripts/import_demo_world.py` 和运行时服务主要依赖中间 import pack，而不是直接依赖
ZhihuRec CSV。因此迁移的第一刀应落在数据 adapter，而不是重写整个后端。

需要保留的 canonical 文件：

```text
manifest.json
topic.jsonl
author.jsonl
app_user.jsonl
question.jsonl
answer.jsonl
question_topic.jsonl
answer_topic.jsonl
query_topic_map.jsonl
hot_answer_snapshot.jsonl
default_profile_seed.json
demo_user_profile_seed.json
demo_persona_profile_seeds.json
evaluation_persona_profile_seeds.json
demo_personas.json
demo_event_replay.jsonl
sponsored_campaign.jsonl
sponsored_campaign_topic.jsonl
sponsored_creative.jsonl
```

---

## 4. MIND 到现有 canonical model 的映射

### 4.1 新闻内容

| MIND 字段 | Canonical/运行时字段 | 规则 |
|---|---|---|
| `news_id` | `answer_id` / 产品层 `article_id` | 校验 `N<digits>` 后提取数字；禁止使用 Python `hash()` |
| `news_id` | `question_id` | 与 `answer_id` 建立 1:1 兼容映射 |
| `title` | `display_title` / `headline` | 使用真实英文标题 |
| `abstract` | `display_summary` / `abstract` | 空值时使用明确的空摘要占位，不生成虚构内容 |
| `category` | 一级 topic | 规范化小写值并生成稳定 ID |
| `subcategory` | 二级 topic | 与一级 category 同时挂到 article |
| `URL hostname` | `author.display_name` / `source_domain` | 只能称 source domain，不能称原始 publisher |
| title entities | 可选 topic/query alias | V1.1 使用，首个 parity 版本可暂不启用 |
| abstract entities | 可选 topic/query alias | V1.1 使用，首个 parity 版本可暂不启用 |

MIND 不提供可靠的新闻发布时间。`create_ts` 使用该新闻在所选行为数据中的
`first_seen_impression_ts`，并在 manifest 中记录：

```text
timestamp_semantics = first_seen_in_selected_mind_impressions
```

任何 freshness 结论都必须使用“首次出现在数据窗口”这一语义，不能称发布时间。

### 4.2 用户和请求

| MIND 字段 | 运行时字段 | 规则 |
|---|---|---|
| `user_id` | `user_id` | 校验 `U<digits>` 后提取数字 |
| `impression_id` | `request_id` | `mind:{split}:{impression_id}` |
| `time` | `event_ts` | 按 MIND 格式解析并统一转 UTC epoch |
| `history` | 初始 profile seed | 仅作为请求前历史，不伪造精确点击时间 |
| impression candidate `N123-0` | `feed_impression` | 真实曝光、负标签候选 |
| impression candidate `N123-1` | `feed_impression` + click | 曝光后生成匹配 request/article 的点击事件 |

点击事件时间使用 impression timestamp 后固定的最小顺序偏移，只用于保证 replay 顺序。
manifest 必须记录该偏移是 adapter sequencing，不是真实 click timestamp。

### 4.3 Topic 层级

现有数据库 topic 是扁平结构。MIND adapter 将：

- category 作为一级 topic；
- subcategory 作为二级 topic；
- article 同时关联 category 和 subcategory；
- `source_rank=0` 表示 category；
- `source_rank=1` 表示 subcategory；
- topic ID 由规范化字符串排序后确定，并写入稳定映射文件。

禁止依赖遍历顺序、进程随机种子或 Python hash 生成 ID。

### 4.4 Hotness

保留当前可解释公式：

```text
hot_score = click_count * 10 + impression_count
```

同时在数据报告中补充：

- impression count；
- click count；
- empirical CTR；
- category exposure share；
- article exposure long tail。

排序模型可以使用 CTR 派生特征，但必须使用平滑和 cutoff-safe 计数，避免目标泄漏。

---

## 5. 目标数据产物

### 5.1 Raw 层

```text
data/mind/
  raw/
    small/
      train/
      dev/
    large/                 # optional
  meta/
    download_manifest.json
    local_checksums.json
```

Raw 层全部加入 `.gitignore`。

### 5.2 Normalized offline 层

```text
build/mind_normalized/
  articles.parquet
  impressions_train.parquet
  impressions_dev.parquet
  id_maps.json
  normalization_manifest.json
```

Normalized 层用于大样本训练和评测，不直接作为在线服务源。

### 5.3 Demo serving 层

```text
build/mind_demo_world/
  ...canonical import pack...
  import_demo_world.sql
```

Demo world 只保留少量高质量 persona 和候选内容，负责本地展示，不承担总体模型结论。

### 5.4 CI fixture

```text
build/mind_demo_fixture/
```

fixture 必须是代码生成的确定性英文新闻样例，不复制受许可约束的完整 raw 数据。

---

## 6. 分阶段实施

## Phase 0：冻结当前基线

### 工作

- 保存迁移前 Git commit；
- 记录当前测试、前端 build 和 smoke 状态；
- 将现有 ZhihuRec 指标标记为 historical；
- 保存当前 API contract 和 model artifact schema version；
- 不修改或删除现有 raw 数据，直到 MIND 路径完整通过。

### 验收

- 能明确指出迁移前 commit；
- 当前测试结果可复现；
- 新旧指标不会写入同一个 `latest.json`。

---

## Phase 1：下载、许可确认和数据检查

### 新增

- `scripts/download_mind.py`
- `scripts/inspect_mind.py`
- `tests/test_inspect_mind.py`

### 修改

- `.gitignore`
- `.env.example`
- `README.md`

### 下载脚本要求

- 参数：`--variant small|large`、`--split train|dev|all`；
- 必须提供 `--accept-license`；
- 使用官方 blob URL；
- 已存在且 checksum 一致时跳过；
- 生成本地 SHA256 manifest；
- 下载失败时保留明确错误，不使用非官方镜像静默 fallback；
- 默认只下载 MIND-small train/dev。

### 检查脚本要求

验证：

- `news.tsv` 列数和 ID 格式；
- `behaviors.tsv` 列数和时间格式；
- impression candidate 的 `-0/-1` 标签；
- 所有 candidate/history news ID 的 metadata coverage；
- train/dev 用户重叠率；
- 每用户 request 数分布；
- 每 request candidate 数和正例数；
- 空 title、abstract、category、subcategory 比例；
- 时间范围和排序异常；
- category/subcategory 基数；
- 数据规模与官方说明是否处于合理范围。

### Gate

在决定最终训练/评测 split 前，必须先根据检查结果确认 train/dev 用户是否足以支持
当前 user-factor ALS。不得预设两者一定重叠。

---

## Phase 2：构建 normalized MIND adapter

### 新增

- `scripts/normalize_mind.py`
- `backend/app/data_contracts/mind.py`
- `tests/test_normalize_mind.py`

### 输出

- article 表；
- item-level impression 表；
- stable user/article/topic ID maps；
- split、时间、label、request 统计；
- raw 输入 checksum 和 normalized fingerprint。

### 数据正确性约束

- 一条 candidate 必须对应一条真实 item-level impression；
- `clicked=1` 必须在相同 request 中存在对应 impression；
- 同一 request 不得跨 train/dev；
- article、user、topic ID 映射在重复运行间保持一致；
- 不能把未曝光文章随机采样成 offline negative；
- history 只能用于 pre-request profile，不得伪造时间；
- train 统计不得读取 dev outcome；
- 所有派生字段必须在 manifest 中记录 provenance。

### 验收

- 相同 raw 输入运行两次得到相同 fingerprint；
- normalized impression 行数等于所有 candidate 数之和；
- 正例数等于所有 `-1` 标签数；
- 没有 orphan user/article/topic；
- 测试覆盖 malformed ID、空 history、多正例 request 和缺失 abstract。

---

## Phase 3：生成 MIND demo world

### 新增

- `scripts/build_mind_demo_world.py`
- `scripts/build_mind_demo_fixture.py`
- `tests/test_mind_demo_world.py`

### 修改

- `scripts/import_demo_world.py`
- `scripts/apply_demo_mysql.py`
- `scripts/init_local.sh`

### Persona 选择

默认选择 3–5 个用户，要求：

- 至少有多个按时间排序的 requests；
- train/eval 区间同时具有正例和负例；
- category 偏好具有差异；
- 候选池能够覆盖其历史与 held-out clicked articles；
- persona 名称基于偏好类别生成，如 `Sports Reader`，不暴露原始用户 ID 语义。

### Replay 生成

每个 MIND impression：

1. 为全部 candidates 生成 `feed_impression`；
2. 对 `-1` candidate 生成匹配同一 request 的 `recommendation_click`；
3. 按 timestamp、impression、candidate 顺序稳定排序；
4. 不生成 raw search events；
5. 搜索事件只在产品交互或独立 intent fixture 中产生。

### Canonical pack 兼容

第一阶段继续输出旧文件名，确保 importer、MySQL、训练代码和 API 可以逐步迁移。
每行必须写：

```json
{
  "source": "mind_small",
  "source_split": "train"
}
```

### 验收

- importer 能生成 SQL；
- MySQL schema 能完整导入；
- 每个 persona 有可评测 request；
- fixture 不依赖 raw MIND 文件；
- `scripts/init_local.sh --smoke-test --product-frontend` 使用 MIND fixture 可通过。

---

## Phase 4：运行时和产品语义迁移

### 配置

新增 `NEWSREC_*` 环境变量，并在一个迁移周期内兼容读取旧 `ZHIHUREC_*`：

- `NEWSREC_DATABASE_URL`
- `NEWSREC_DEMO_SEED_DIR`
- `NEWSREC_EVENT_MODE`
- `NEWSREC_REQUEST_ID_PREFIX`
- `NEWSREC_KAFKA_*`

默认值：

```text
app_name = NewsIntentRec Backend
request_id_prefix = newsrec
demo_seed_dir = build/mind_demo_world
database = newsrec_demo
```

旧变量被使用时输出一次明确 deprecation log，不能静默永久兼容。

### API 产品字段

产品响应迁移为：

```text
article_id
headline
abstract
source_domain
categories
```

后端内部 SQL 暂时可以：

```sql
answer_id AS article_id
question_title AS headline
answer_summary AS abstract
```

API 迁移采用一次明确版本切换，不长期同时返回两套重复字段。

### 路由

- `/answers/{id}` -> `/articles/{id}`
- event payload `answer_id` -> `article_id`
- sponsored creative 对外使用 `article_id`
- debug 字段、日志和 metrics label 使用 article/news 术语。

### 主要修改文件

- `backend/app/config.py`
- `backend/app/schemas/*.py`
- `backend/app/routers/answers.py`
- `backend/app/repositories/content_dao.py`
- `backend/app/repositories/mysql.py`
- `backend/app/repositories/training_data.py`
- `backend/app/events/*.py`
- `product-frontend/src/api/types.ts`
- `product-frontend/src/api/client.ts`
- `product-frontend/src/components/PostCard.tsx`
- `product-frontend/src/pages/*.tsx`
- API、event、frontend tests

### 前端

- Reddit 风格社区名称改为新闻 category/source；
- `Posted by u/...` 改为 `Source: ...`；
- `Comments` 改为 `Read article` 或 `Details`；
- 展示 headline、abstract、category/subcategory；
- sponsored 内容继续明确标注；
- 页面中不出现 ZhihuRec、answer、question 或虚构 Reddit community 文案。

### 验收

- OpenAPI 中不再暴露旧产品字段；
- 前端类型中不再出现 `answer_id/question_title/answer_summary`；
- 运行日志和 UI 中不出现 ZhihuRec；
- 内部兼容表名只允许存在于 SQL/repository 层，并有说明。

---

## Phase 5：搜索与 intent feedback 重建

### 搜索索引来源

搜索使用真实 MIND 内容：

- title；
- abstract；
- category；
- subcategory；
- title/abstract entities（第二阶段）。

### Query resolver

将当前 token-ID exact map 改为英文文本 resolver：

1. normalize lowercase/whitespace；
2. category/subcategory exact alias；
3. entity alias；
4. title/abstract lexical match；
5. 无匹配时返回明确的 no-result，不伪造 topic。

首版可以使用 MySQL FULLTEXT 或轻量 BM25；选择前需用 MIND-small 测量索引规模和延迟。

### Search feedback

产品中的真实本地交互仍进入：

- `search_query`
- `search_result_click`
- profile recent queries
- topic/category weight update
- 后续 feed recall/ranking

### 离线实验边界

新增独立的 deterministic intent scenarios：

```text
persona current profile
  -> inject an explicit category/entity query
  -> compare next-feed category alignment and diversity
```

指标文件单独存放：

```text
docs/metrics/mind_intent_mechanism.json
```

它只能支持“机制按设计改变候选和排序”的结论，不能支持真实用户收益结论。

### 验收

- 搜索结果来自真实 MIND title/abstract；
- 搜索 query 会改变 profile；
- 下一次 feed 的 debug reason 能解释 query 影响；
- 推荐主指标与 intent mechanism 指标完全分开。

---

## Phase 6：模型训练与离线评测重建

### 6.1 数据分层

模型证据不能只来自 3 个 demo persona。需要分开：

- demo world：在线演示；
- normalized MIND-small：训练和离线评测；
- MIND-large：可选扩展。

### 6.2 ALS/FAISS

先检查 train/dev 用户重叠：

- 若重叠足够：报告 known-user collaborative retrieval；
- 若重叠不足：在 train 内做 chronological held-out 评测；
- dev 新用户单独报告 cold-start/content/category arm；
- 不允许为不存在的 dev user factor 使用成功形状的默认向量。

模型 artifact 必须记录：

- raw/normalized fingerprint；
- split；
- user/item count；
- factors；
- similarity；
- known-user coverage；
- training cutoff；
- ID map fingerprint。

### 6.3 LightGBM

训练样本严格来自真实 impression candidates：

- clicked candidate = positive；
- exposed non-clicked candidate = negative；
- request 不拆分；
- 全部统计特征 cutoff-safe；
- category/content features不得读取未来点击；
- 训练和评测保持官方 split 或预注册的 chronological split。

### 6.4 必须报告的指标

推荐：

- Recall@5、Recall@10；
- NDCG@5、NDCG@10；
- MRR；
- candidate Recall@K；
- category coverage/diversity；
- known-user coverage；
- request failure count。

Pointwise：

- ROC AUC；
- PR AUC；
- log loss；
- calibration 简表。

系统：

- feed API p50/p95 latency；
- search API p50/p95 latency；
- import/build duration；
- model artifact size。

### 6.5 评测 arms

至少比较：

1. popularity；
2. category-profile manual ranker；
3. ALS recall + manual ranker；
4. ALS recall + LightGBM；
5. content/category fallback；
6. intent-feedback mechanism arm（单独报告，不能混入主推荐胜负）。

### Gate

如果 ML arm 没有超过 baseline，保留负结果，并把结论写成：

> 分阶段系统使检索和排序变得可度量；已测试模型尚未证明其相对最强基线具有可靠提升。

不得为了简历叙事删除负结果或更换指标。

---

## Phase 7：数据分析、文档与项目叙事

### 替换文档

- `README.md`
- `docs/data_analysis_report.md`
- `docs/v1_metrics.md`，迁移后重命名为 `docs/metrics.md`
- `docs/hci_report.md`
- `docs/v1_api_contract.md`
- `docs/v1_local_runbook.md`
- `plan/project_brief_zh.md` 增加 superseded 说明，不重写历史原文

### 新数据分析报告

至少覆盖：

- train/dev 数据规模；
- user activity distribution；
- candidates per impression；
- positives per impression；
- category/subcategory 分布；
- article exposure long tail；
- CTR 分布；
- history length；
- cold-start user/article 比例；
- train/dev user/article overlap；
- title/abstract 缺失率；
- demo world 与完整 MIND-small 的差异。

### README 首页必须说清

1. 使用的是 public MIND；
2. MIND 提供真实曝光和点击，但没有搜索日志；
3. 搜索反馈是产品机制，不是原始数据中的 observed search behavior；
4. 当前指标的 split、样本规模和限制；
5. 项目与 Microsoft 官方/实习工作无关。

### 面试故事

推荐主线：

> 我围绕公开 Microsoft MIND 数据集重建了内容推荐原型。核心工程变化是将大型、
> 感知曝光的离线训练流水线与小型确定性在线服务世界分离，同时让在线搜索和点击事件
> 继续使用同一条画像反馈回路。

可讲的 trade-off：

- 为什么选真实 impression negative，而不是随机 negative；
- 为什么 demo world 和训练世界必须分离；
- 为什么 MIND 没有 search logs 时不能声称 search lift；
- 为什么保留兼容 schema，而不是先做大规模表重命名；
- known-user ALS 与 cold-start user 的不同处理；
- 如何通过 fingerprint、cutoff 和 request-level split 防止泄漏。

---

## Phase 8：最终清理和发布审计

### 删除/替换

- ZhihuRec downloader、inspector、builder 和 EDA 入口；
- ZhihuRec 默认路径和环境变量默认值；
- synthetic Zhihu topic/query label assets；
- 当前 ZhihuRec model artifacts；
- 当前 ZhihuRec metrics JSON；
- UI 中的 Reddit/Zhihu 临时文案；
- SQL comments 中把 ZhihuRec 当当前数据源的描述。

历史文件只有在 MIND 全链路验证通过后删除。不要在迁移中途破坏回退路径。

### 全仓检查

最终执行：

```bash
rg -n "ZhihuRec|zhihurec|知乎|answer_id|question_title|answer_summary" .
```

允许的残留仅包括：

- Git 历史无法检查；
- 明确标记的 migration compatibility SQL/repository code；
- `project_brief_zh.md` 的历史说明。

所有其他残留必须处理。

---

## 7. 测试计划

### 单元测试

- MIND ID 解析；
- timestamp 解析；
- impression label 解析；
- stable ID mapping；
- topic hierarchy mapping；
- first-seen timestamp；
- request-level event generation；
- history seed；
- malformed TSV；
- empty abstract/category；
- multi-positive impression；
- train/dev leakage guards。

### Contract 测试

- canonical import pack required files；
- importer SQL；
- API article fields；
- event schema article IDs；
- search query resolution；
- model artifact compatibility；
- deprecated environment variable behavior。

### 集成测试

- MySQL schema + MIND fixture import；
- feed -> click -> profile -> next feed；
- search -> search click -> profile -> next feed；
- duplicate event idempotency；
- sponsored insertion；
- Kafka raw event -> consumer -> profile；
- training extraction uses only exposed candidates。

### 前端测试

- article card rendering；
- category/source labels；
- feed impression tracking；
- article detail navigation；
- search query and click tracking；
- persona switch；
- sponsored label；
- no Zhihu/Reddit placeholder language。

### 最终命令

```bash
python -m ruff check backend scripts tests
python -m mypy
python -m pytest -q

cd product-frontend
npm test -- --run
npm run build
```

另外执行 MySQL/Kafka integration 和完整 bootstrap smoke。

---

## 8. Definition of Done

只有同时满足以下条件，才算完成：

- [x] 默认数据源为 MIND-small；
- [x] raw MIND 数据不进入 Git；
- [x] 下载流程包含显式许可确认；
- [x] MIND adapter 输出稳定、可追踪的 canonical 数据；
- [x] MySQL 可以从 MIND fixture 和 MIND demo world 初始化；
- [x] API 和前端使用 article/news 语义；
- [x] 产品界面不存在旧数据集或社区 placeholder；
- [x] 推荐训练只使用真实 exposure/click label；
- [x] train/dev 或 chronological split 没有 request 泄漏；
- [x] ALS 对 unknown user 的行为被明确处理；
- [x] 搜索机制没有被包装成 MIND observed search；
- [x] 主推荐指标和 intent mechanism 指标分开；
- [x] 最新数据分析和 metrics 来自 MIND；
- [x] README 清楚说明 public dataset、license 和项目独立性；
- [x] 全部现有测试、前端 build、MySQL/Kafka integration 和 smoke 通过；
- [x] 旧数据源当前 artifacts 和默认入口已删除；
- [x] 最终全仓残留审计通过。

---

## 9. 建议提交顺序

每个提交保持可验证和可回退：

1. `docs: add MIND migration plan`
2. `feat: add MIND download and inspection tooling`
3. `feat: normalize MIND news and impression data`
4. `feat: build MIND demo world and deterministic fixture`
5. `refactor: make import and runtime dataset-neutral`
6. `refactor: expose article-oriented API contracts`
7. `feat: rebuild news search and intent feedback`
8. `feat: train and evaluate on normalized MIND impressions`
9. `refactor: migrate frontend to news product semantics`
10. `docs: replace ZhihuRec reports with MIND evidence`
11. `chore: remove legacy ZhihuRec runtime paths`

不得把数据 adapter、API breaking change、模型结果和旧代码删除压进一个不可审查的大提交。

---

## 10. 工作量估计

以一名熟悉当前仓库的工程师计算：

| 阶段 | 估计 |
|---|---:|
| 下载、检查、normalized adapter | 1.5–2 天 |
| demo world、fixture、import | 1.5–2 天 |
| API/config/product 语义迁移 | 1.5–2 天 |
| search/intent feedback | 1–2 天 |
| 训练与离线评测重建 | 2–3 天 |
| 前端、文档、清理和最终验证 | 1.5–2 天 |
| **总计** | **9–13 个工程日** |

如果只追求“能跑的 MIND Demo”，约 3–4 天；但那不包含可信的大样本训练、评测重建、
产品语义清理和完整证据链，不应视为本计划完成。

---

## 11. 第一执行批次

第一批只做可逆、低风险工作：

1. 新增 MIND-small 下载脚本；
2. 新增 raw inspector；
3. 生成数据规模、缺失率和 train/dev overlap 报告；
4. 确定 ALS 的最终 split 策略；
5. 再实现 normalized adapter。

在 train/dev overlap、candidate label 和缺失字段尚未真实检查前，不开始修改 API、
数据库字段或删除 ZhihuRec 路径。
