# MIND 搜索相关性评估

## 范围与证据边界

搜索升级在完整的规范化 MIND-small 目录上评估：

- 65,238 篇文章；
- 48 个固定英文查询；
- 24 个校准查询和 24 个留出测试查询；
- 词法、同义词、自然语言改写、拼写/噪声及无关/OOD 切片；
- 来自词法、BM25、稠密和混合候选项的 1,239 条汇总标注；
- AI 辅助标注，以及用户批准的 12 条分层人工抽样检查。

MIND 不包含观察到的搜索日志。这些指标衡量固定标注集上的离线相关性，
并不估计点击率、用户因果收益或生产质量。在线演示仍只索引
`build/mind_demo_world` 中的 174 篇文章。由于 BM25 IDF 的量级取决于语料规模，
演示制品保留全语料融合权重，但使用单独纳入版本控制的
`evaluation/search_relevance/online_demo_config.json` 置信度配置。
该配置属于运行时行为设置，不纳入所报告的全语料相关性指标。

机器可读证据：

- `docs/metrics/mind_search_relevance.json`
- `docs/metrics/mind_search_latency.json`
- `evaluation/search_relevance/queries.jsonl`
- `evaluation/search_relevance/qrels.jsonl`
- `evaluation/search_relevance/label_manifest.json`
- `evaluation/search_relevance/calibration_report.json`
- `evaluation/search_relevance/selected_config.json`

## 已实现的检索路径

```text
数值型 query_key
  -> 规范化并保留

精确的显示名/类别别名
  -> 高精度主题查找

其他自由文本
  -> 确定性 BM25 前 50 项
  -> all-MiniLM-L6-v2 查询嵌入
  -> 规范化 FAISS IndexFlatIP 前 50 项
  -> 加权倒数排名融合
  -> 校准后的置信度门控
  -> 只保留高置信度文章
  -> 汇总文章主题，得到规范 query_key
  -> 持久化搜索意图，供现有信息流反馈回路使用
```

在线实现位于：

- `backend/app/search_retrieval.py`
- `backend/app/repositories/query_resolver.py::resolve_search_query`
- `backend/app/repositories/content_dao.py::load_search_candidates`
- `backend/app/repositories/mysql.py::MysqlRuntimeRepository.search`

搜索不会再用不相关热门文章填满不足一页的结果。低置信度自由文本查询返回
422 `unresolved_query`。混合搜索制品缺失或不兼容时返回 503
`search_index_not_ready`，并使就绪检查失败，而不是静默回退。

## 校准

`scripts/calibrate_search_relevance.py` 仅使用 24 个校准查询评估了 3,456 组配置。
合格配置必须满足：

- 拒绝准确率为 `1.0`；
- 误拒率不超过 `0.05`。

选定配置如下：

| 参数 | 值 |
|---|---:|
| BM25 权重 | 1.0 |
| 稠密检索权重 | 0.5 |
| RRF k | 10 |
| 各通道候选深度 | 50 |
| 稠密检索接受阈值 | 0.42 |
| 存在 BM25 证据时的稠密检索下限 | 0.30 |
| BM25 证据阈值 | 20.0 |
| 融合间隔阈值 | 0.004 |

模型为修订号 `1110a243fdf4706b3f48f1d95db1a4f5529b4d41` 的
`sentence-transformers/all-MiniLM-L6-v2`。文档嵌入经过 L2 规范化，
因此 `IndexFlatIP` 对该目录执行的是精确余弦检索。

## 留出集结果

下表使用 24 个留出查询，其中 19 个相关查询、5 个 OOD 查询。

| 实验分组 | Recall@5 | Recall@10 | NDCG@10 | MRR@10 | OOD 拒绝准确率 | 误拒率 |
|---|---:|---:|---:|---:|---:|---:|
| 旧版词法搜索 | 0.1378 | 0.2895 | 0.2854 | 0.3158 | 0.0 | 0.0 |
| BM25 | 0.4334 | 0.6847 | 0.6790 | 0.7444 | 1.0 | 0.1053 |
| 稠密检索 | **0.6492** | **0.8806** | **0.8319** | **0.8772** | 1.0 | 0.0 |
| 混合检索 | 0.5966 | 0.8122 | 0.8131 | 0.8596 | 1.0 | 0.0 |

混合检索相对旧版词法路径：

- NDCG@10 变化：`+0.5277`，配对 95% 置信区间 `[+0.3130, +0.7257]`；
- Recall@10 变化：`+0.5227`，配对 95% 置信区间 `[+0.3122, +0.7174]`；
- MRR@10 变化：`+0.5439`，配对 95% 置信区间 `[+0.3158, +0.7544]`；
- OOD 拒绝准确率：`0.0 -> 1.0`。

稠密检索是整体留出评估中最强的分组。混合检索的整体 NDCG@10 未超过稠密检索，
项目保留了这一负面结果。混合检索在拼写/噪声切片上最强（NDCG@10 为 `0.8945`，
稠密检索为 `0.6372`），同时保持了词法加语义的产品设计目标。
预先声明的上线门槛将混合检索与旧版在线路径比较并已通过，因此 `hybrid_v1`
是默认方案，稠密检索则保留为已测量的替代方案。

## 运行时与制品安全

- 制品元数据记录模型修订号、来源指纹、文档数、嵌入维度、混合配置和 SHA-256 哈希。
- 在线加载会拒绝缺失文件、文件损坏、来源指纹不匹配、不支持的模式或不可用的本地编码器。
- `/readyz` 暴露 `search_index` 依赖项。
- Prometheus 暴露搜索解析结果和检索耗时。
- BM25/稠密搜索制品与现有 ALS FAISS 制品相互独立。

在包含 174 篇文档的演示索引上，预热后的进程内检索在 100 次调用中的
p50 为 `6.433 ms`、p95 为 `9.568 ms`。该测量不包含 HTTP、MySQL、事件写入、
并发和生产容量。

## 复现

```bash
python scripts/build_search_index.py \
  --corpus full \
  --model-revision 1110a243fdf4706b3f48f1d95db1a4f5529b4d41 \
  --config evaluation/search_relevance/selected_config.json

python scripts/calibrate_search_relevance.py

python scripts/eval_search_relevance.py \
  --config evaluation/search_relevance/selected_config.json

python scripts/build_search_index.py \
  --corpus demo \
  --model-revision 1110a243fdf4706b3f48f1d95db1a4f5529b4d41 \
  --config evaluation/search_relevance/selected_config.json \
  --online-config evaluation/search_relevance/online_demo_config.json

python scripts/benchmark_search_retrieval.py --iterations 100
```

## 限制

- 1,239 条标注中只有 12 条经过人工抽样检查，其余均由 AI 辅助生成。
- 留出集仅包含 24 个查询，因此置信区间仍较宽。
- 候选池汇总可减少未标注文档偏差，但无法完全消除。
- 全目录相关性评估与 174 篇文档的在线服务属于不同分布。
- 根据高排名文章主题得到的规范 `query_key` 只是兼容桥梁，不能完整表达自由文本查询的语义。
- 不存在在线搜索日志，因此没有点击率或因果验证。
