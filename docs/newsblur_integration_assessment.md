# NewsBlur 本地源码与 NewsIntentRec 集成评估

调研日期：2026-09-17。NewsBlur 路径：`E:/APPs/GitHub downloads/NewsBlur`，提交：`15b2ae60da271790a5143bf903add84b92ee7f0c`。目标项目：`E:/postgraduatelearning/paper-writing/hkl-rec` 当前工作区，包括已有未提交修改。

本次是静态源码调研，未启动 NewsBlur、未运行其测试、未修改业务代码；以下成本为相对复杂度判断，不是实测工期或效果承诺。优先通过代码图定位；目标项目部分图节点与磁盘内容不一致，已回到当前文件核对关键实现。

## 核心判断

NewsBlur 最值得引入的是可控的阅读与筛选能力：显式兴趣规则、收藏与已读、保存搜索、跨来源报道分组。保留 NewsIntentRec 的 FastAPI、React、PostgreSQL、事件链路及现有排序，按功能改写接入，比整体嵌入 NewsBlur 更合适。

NewsBlur 的主要技术组成是 Django、Backbone.js/jQuery、PostgreSQL、MongoDB、Redis、Celery、Elasticsearch，以及用于正文等处理的 Node 服务。其 Python 模块也普遍引用 Django settings、MongoEngine 和 Redis，通常不能直接 import 到当前项目运行。参考 `ARCHITECTURE.md`、`apps/analyzer/models.py`、`apps/search/models.py`、`node/package.json`。

## 实际存在的几种推荐机制

### 1. 显式规则评分

`apps/analyzer/models.py:459` 的 `compute_story_score` 综合来源、作者、标签、标题、正文、URL 和可选 AI prompt 分数。传统规则不是点击率模型，而是匹配用户保存的偏好。

- 常见分值：喜欢 `+1`、中性 `0`、不喜欢 `-1`、强烈不喜欢 `-2`。
- 非零 AI prompt 分数先返回；否则属性规则中的强负反馈优先，其次正反馈，再其次普通负反馈；无属性结果时才使用来源规则。
- 因此不能笼统地说“所有来源屏蔽必定压过一切”，也不能把一个负分直接当成用户承诺意义上的永久屏蔽。
- 有来源、文件夹、全局作用域及作用域索引优化；这些规则适用范围与本项目的 `source_space` 是不同概念。

`classifier_title_matches`（同文件第 558 行）使用不区分大小写的匹配和 Unicode 词首边界。中文字符也属于词字符，因此中文连续句子中的词可能被排除。例如从代码逻辑推导，标题“关注人工智能发展”中的“人工智能”前面是汉字，可能无法命中。中文应单独采用分词、短语或字符匹配策略。

### 2. 向量发现

`apps/search/models.py` 的 `DiscoverStory` 包含文章向量生成、余弦检索及多篇文章向量的均值归一化。当前实现调用 `text-embedding-3-small`，再投影向量；检索依赖 Elasticsearch。

这适合参考“相关文章”“基于近期阅读发现内容”的流程，不是一个已经训练好的、可直接提升本项目指标的推荐模型。`generate_combined_story_content_vector`（第 1071 行）也不能不加检查地复制：需要处理空向量、缺失向量、维度一致性与零范数。

### 3. 相似报道分组

`apps/clustering/models.py:218` 的 `find_title_clusters` 使用规范化标题精确匹配、关键词重叠与并查集。虽然旧注释写 Jaccard，当前模糊匹配公式实际为交集大小除以较小词集合大小（overlap coefficient）。

`find_semantic_clusters`（第 382 行）实际使用 Elasticsearch `more_like_this`，当前查询文本取标题，并搜索索引中的标题与正文，再增加标题词重叠校验。它与 `DiscoverStory` 的 embedding 检索不是同一套实现。

结果区分标题相似和相关报道，限制跨来源、时间窗口和查询预算，并支持附加分组信息或折叠列表。英文停用词、空格分词和词干处理需要针对中文调整。相关报道不能自动等同于同一事件，更不能把多源重复转载当成多份独立证据。

### 4. 简报选文与 AI 生成

`apps/briefing/scoring.py:36` 的 `select_briefing_stories` 在候选集上结合阅读热度、来源互动、用户打开来源的频次、新鲜度和规则匹配。基础设计权重依次约为 40%、20%、20%、10%、10%；实际规则贡献取决于匹配类型，并另有低频来源加权、每来源数量限制、已读处理和分区配额。

选文后才由 `apps/briefing/summary.py` 生成简报。该逻辑只说明本地版本的简报模块，不代表所有 NewsBlur 页面共用同一排序公式。`apps/recommendations/models.py` 主要是订阅源推荐和反馈模型，也不是论文式神经新闻排序模型。

## 集成功能比较

| 能力 | NewsBlur 参考位置 | 当前项目差距与接入建议 | 复杂度／优先级 |
|---|---|---|---|
| 显式兴趣规则 | `apps/analyzer/models.py`、`views.py` | 当前已有点击、点赞、点踩、停留形成的衰减画像；补充可编辑的来源、主题、关键词规则，显示命中理由 | 中／第一批 |
| 收藏、标签、笔记 | `apps/reader/views.py:5212`、`apps/rss_feeds/models.py` 的 `MStarredStory` | 本次检查未发现相应业务接口；先实现收藏列表和取消收藏，再考虑笔记、高亮 | 低至中／第一批 |
| 已读／未读管理 | `apps/reader/views.py` 的 read/unread 接口 | 现有曝光、点击、停留和会话去重，不等于跨会话阅读状态；增加显式已读、撤销已读和只看未读 | 中／第一批 |
| 保存搜索／跟踪主题 | `apps/rss_feeds/models.py:5310` 的 `MSavedSearch` | 将搜索词和筛选条件保存为常用入口；后续才考虑新结果提示；区别于普通搜索历史 | 低至中／第一批 |
| 跨来源报道分组 | `apps/clustering/models.py` | 当前 Live 有相邻标题近重复抑制和来源打散，尚不等于持久化报道分组；新增分组成员和代表报道 | 中至高／第二批 |
| 相关文章与阅读兴趣向量 | `apps/search/models.py` 的 `DiscoverStory` | MIND 已有语义检索工件，Live 当前搜索是文本匹配加时效；为 Live 单独建立索引，不混用 MIND 工件 | 中至高／第二批 |
| AI 摘要、问答、每日简报 | `apps/ask_ai/`、`apps/briefing/` | 用已获取的正文或明确标记的摘要生成；异步处理、缓存、保留原文引用、记录成本 | 高／后续 |
| 订阅源管理、OPML、自适应抓取 | `apps/feed_import/`、`apps/rss_feeds/` | 若产品扩展为 RSS 阅读器再引入；当前 GDELT 批次发现不能直接套用每个 Feed 的抓取调度 | 中至高／按需求 |

## 推荐的接入边界

### 显式偏好与行为画像分开保存

建议的偏好身份为 `(user_id, source_space, target_type, target_value)`，目标类型先支持 `source_domain`、主题和标题短语。作者暂缓：当前 `ArticleCardResponse` 没有统一作者字段，MIND 的八个源字段也没有作者。

用户动作应明确区分：

- “减少此类内容”：可撤销的软偏好，用于排序或筛选。
- “屏蔽此来源／关键词”：明确的硬约束，不被推荐加分抵消。
- “重置系统学习的兴趣”：默认不应悄悄删除用户手动订阅、屏蔽和收藏；单独定义清除入口。

当前项目接入点：`backend/app/profiles/signals.py`、`backend/app/repositories/profile_v2_dao.py`、`backend/app/services/profile.py`、`product-frontend/src/components/PostCard.tsx` 和 `product-frontend/src/pages/ProfilePage.tsx`。

推荐流程可为：候选加载 → 硬屏蔽 → 原有排序加可选偏好特征 → 多样性处理 → 分页与理由。硬屏蔽需在候选截断、分页判断前得到正确处理，否则会出现空页或错误的 `has_more`。单独定义搜索是否尊重屏蔽，避免用户主动检索时出现无法解释的结果缺失。

先在 Live 或独立实验入口验证偏好规则，不修改 MIND 默认评估口径。用户规则即时生效属于产品可控性；是否改善推荐效果需要另行实验。

### 阅读状态采用当前数据库与事件机制

建议新增 PostgreSQL 用户文章状态，以 `(user_id, source_space, article_id)` 唯一标识，记录收藏时间、已读时间及后续笔记。引用现有新闻记录，初版无需照搬 NewsBlur 的收藏正文副本与 MongoDB 模型。

已曝光不等于已读；文章点击也不应自动等同于认真阅读。显式“标为已读”和基于可见停留的自动标记需要不同来源标识。状态写入与事件投递保持一致，避免接口重试重复累加画像。现有 `EventTrackType` 没有收藏类事件，需同时更新契约、存储和消费逻辑；取消收藏如何影响画像也需定义。

本项目已有 `product-frontend/src/feed/useFeedSessionRestoration.ts`，不要重复建设返回列表的位置恢复；真正新增的是跨会话、跨设备的阅读状态。

### Live 报道分组与语义索引独立建立

在 `backend/app/live_news/ranking.py` 和 `backend/app/news_spaces/live.py` 附近接入新模块。现有 Live 基础分为 `0.65 × 新鲜度 + 0.20 × 来源质量 + 0.15 × 完整度`，再做来源和语言多样性处理，评分函数尚未读取用户兴趣。

建议先实现“相关报道”附加列表，再验证是否适合折叠成同一事件；中文、英文及跨语言匹配分别评估。索引记录模型版本、内容版本和语言，失败时回退当前排序。复用 FAISS 的技术经验可以，复用 MIND 的索引内容和用户表示不可以。

### AI 缓存必须覆盖正文变化

`apps/ask_ai/models.py:9` 的缓存可以参考异步与复用思路，但不能直接照搬键设计。你当前正文 Worker 会更新正文和结构版本，应将 `source_space`、文章标识、输入内容指纹、模型、提示词版本、问题及必要用户范围纳入缓存身份，防止返回旧正文摘要。缺少正文时不能展示为“全文总结”。

## 已有能力，不建议整体替换

- 当前已具备正文 Worker、来源策略、抓取安全检查、失败重试和结构化正文。NewsBlur 的 `MStory.fetch_original_text` 与 Node Mercury 服务可作为抽取质量对照，不应直接替换当前链路。
- 当前 `content_worker.py:149` 已支持指数退避、抖动和数字形式 Retry-After。NewsBlur 的调度提供每 Feed 调整频率的参考，并非本项目完全缺少重试能力。
- 保留现有 FastAPI 鉴权、PostgreSQL 事实源、Outbox/Kafka；不用为收藏或兴趣规则引入整套 Django、MongoDB、Redis 和 Celery。
- Backbone 页面适合研究交互，React 页面需要重新实现。移动客户端、支付会员、社交动态不是当前新闻推荐项目的优先范围。

## 复用方式与验证边界

可小范围移植的是解耦后的规范化、规则匹配、分组等函数和相应测试思路；ORM、路由、缓存、任务队列和前端组件通常需要改写。纯函数也必须经过中文适配和行为验证。

本地 `LICENSE.md` 标明 MIT，并要求复制或实质复用软件时保留版权与许可文本；第三方依赖和素材需分别确认。此处仅记录仓库许可事实。

后续集成验收应覆盖：账户与空间隔离、规则冲突、中文匹配、幂等和撤销、分页不漏项不重复、缓存失效，以及对现有 MIND 评估的回归检查。报道分组另需同事件／仅同主题／重复转载的人工样例。现阶段未运行这些验证，因此不声称集成已经完成或会提升离线指标。
