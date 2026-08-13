# 混合搜索面试深度解析

## 稳妥的项目描述

**分类：代码已实现，并有离线证据。**

项目将基于 `LIKE` 的自由文本路径升级为精确别名、BM25、sentence-transformer 嵌入、
FAISS 余弦检索、倒数排名融合和校准后的 422 拒绝门控。同时建立了可复现的相关性基准，
并保留搜索到信息流的意图反馈回路。

主导程度为**[主导度待确认]**。仓库能够证明系统行为，但不能证明每个设计决策由谁亲自主导。

## 简历要点

> [主导度待确认] 将新闻自由文本搜索从 exact/prefix/contains/LIKE 升级为
> exact alias + BM25 + sentence-transformer/FAISS 混合检索，构建 48-query、
> 1,239 条 pooled qrels 的离线评测；在 held-out 集上将 NDCG@10 从
> 0.2854 提升至 0.8131、Recall@10 从 0.2895 提升至 0.8122，并将 OOD
> 正确拒绝率从 0 提升至 1.0，同时保留 422 拒绝语义与搜索意图反哺 Feed。

面试时必须补充：标签以 AI 辅助为主，仅有 12 条分层人工抽查；这不是 CTR 或
线上因果收益。

## 1 分钟版本

原来的搜索会先用 exact、prefix、contains 和文章 `LIKE` 把自由文本压成一个
topic key，再按 topic 找文章。它能运行，但对同义词、改写、拼写错误和无关
查询没有相关性证据，而且候选不足时会用热门文章补齐。我先冻结旧算法并建立
48 条查询、1,239 条 pooled qrels 的评测集，然后实现 BM25 和
all-MiniLM-L6-v2 + FAISS 两路召回，用 RRF 融合，并在 calibration split 上
校准置信度阈值。线上保留 numeric/exact alias 的高精度路径；自由文本只有在
置信度足够时才返回结果，否则 422，也不再热门补齐。held-out 上 hybrid 的
NDCG@10 从 0.2854 提升到 0.8131，OOD 拒绝率从 0 到 1.0。dense 单路整体略高，
但 hybrid 在拼写噪声 slice 最强，这个负结果和取舍都保留在报告里。

## 5 分钟结构

1. **问题定义**：功能测试证明链路，不证明语义相关性。
2. **旧链路**：`query_text -> query_key -> topic lookup + LIKE + hot backfill`。
3. **评测先行**：先冻结 lexical baseline，再做固定 query split 和 candidate
   pooling，避免只展示几个成功例子。
4. **双路召回**：
   - BM25 负责关键词、实体、拼写仍可匹配的 lexical evidence；
   - MiniLM + FAISS 负责同义词和自然语言改写。
5. **融合**：选择 weighted RRF，而不是直接相加 BM25 和 cosine 分数。
6. **拒绝**：排名与“是否应该回答”分开；使用 dense evidence、BM25 evidence
   和 fusion margin 校准 422。
7. **兼容现有系统**：从高置信 article hits 聚合 topics，映射到 canonical
   `query_key`，继续写 search event 和 recent query，从而影响后续 feed。
8. **可靠性**：artifact fingerprint/hash/model revision/readiness/503，不静默
   fallback。
9. **结果**：hybrid 显著超过旧 lexical；dense 单路总体最高，hybrid 在 typo
   slice 最强。
10. **边界**：AI-assisted labels、小 query set、无真实 search log、无 CTR。

## 核心代码路径

```text
POST /search
-> backend/app/routers/search.py::search
-> backend/app/services/search.py::SearchService.search
-> backend/app/repositories/mysql.py::MysqlRuntimeRepository.search
-> backend/app/repositories/query_resolver.py::resolve_search_query
-> backend/app/search_retrieval.py::HybridSearchIndex.search
-> backend/app/search_retrieval.py::build_hybrid_search_result
-> backend/app/repositories/content_dao.py::load_search_candidates
-> event/profile update
-> SearchResponse
```

离线路径：

```text
scripts/build_search_index.py
-> evaluation/search_relevance/queries.jsonl + qrels.jsonl
-> scripts/calibrate_search_relevance.py
-> scripts/eval_search_relevance.py
-> docs/metrics/mind_search_relevance.json
```

## 三层追问

### 1. 为什么不只使用嵌入检索？

**第一层：** 稠密检索擅长处理语义改写，但可能漏掉稀有词元、拼写错误和精确实体。
BM25 可以补充明确的词法证据。

**第二层：** 在该基准上，稠密检索整体最强，混合检索则在拼写/噪声切片上最强。
准确的结论不是“混合检索总是获胜”，而是两个通道的失败模式具有互补性。

**第三层：** 如果流量结构不再以噪声/实体查询为主，额外 BM25 通道的收益可能不足以抵消复杂度。
保留稠密检索分组和评估框架，可以让这一决策被量化。

### 2. 为什么使用 RRF 而不是分数归一化？

BM25 与余弦相似度的分数分布互不相关。RRF 使用排名位置，避免假设原始分数已经校准。
代价是舍弃部分分数量级信息，并引入 `k` 和通道权重。

### 3. 为什么拒绝机制与排序分离？

排序器即使面对无关查询也总能产生首位结果。直接返回会把“坏候选项中的最佳项”包装成
错误的成功结果。因此系统先检查通道证据和校准阈值，再决定排序列表能否成为成功搜索响应。

### 4. 为什么保留精确别名？

精确别名经过整理，具有确定性、低成本和高精度。将其送入嵌入检索只会增加延迟与歧义。
混合短路径不保留前缀/包含别名，因为它们更容易错误截获语义查询。

### 5. 自由文本如何继续影响信息流？

混合检索返回文章 ID。解析器汇总高排名结果的主题，对子类别赋予略高权重，
再选择现有 `query_topic_map` 键。该键通过现有事件/画像路径保存。
这种方式保持了兼容性，但存在信息损失，不能视为完整的查询嵌入画像。

### 6. 制品过期或缺失时会发生什么？

加载器会验证模式、来源指纹、ID 映射、文件哈希、模型 ID/修订号和索引行数。
已配置的混合部署会使就绪检查失败并返回 503，而不会静默用词法回退冒充请求的混合服务。

## 最可能被追问的薄弱点

- qrels 不是大规模人工金标准基准。
- 留出查询只有 24 个。
- 稠密检索整体优于混合检索。
- 全目录评估与演示服务的语料规模不同。
- query-key 兼容桥梁压缩了更丰富的语义意图。
- 尚未运行生产并发、内存或 API 延迟基准。

## 可以写与不应写

| 可以写 | 不应写 |
|---|---|
| BM25 + sentence-transformer + FAISS 混合检索 | 生产级搜索平台 |
| 可复现的离线相关性评估 | 在线点击率提升 |
| 固定标注集上的留出 NDCG/Recall/MRR | 人工金标准基准 |
| 校准后的低置信度拒绝 | 完美语义理解 |
| 制品指纹/哈希/就绪治理 | 向量数据库或分布式搜索 |
| 如实记录稠密与混合检索消融 | 混合检索是整体最佳分组 |

## 最佳精简答辩

> 我不是先把 embedding 接进接口再找几个好例子，而是先冻结旧 lexical baseline，
> 再用同一批 query/qrels 比较 lexical、BM25、dense 和 hybrid。最终 hybrid
> 显著超过旧线上路径，并在 typo/noise slice 最强；dense 单路总体略高，这个
> 负结果我也保留。上线时我用预先冻结的 gate 决定默认策略，同时用 422 和
> readiness 保护低置信度与 artifact 故障。
