# 新闻正文解析修复与验证（2026-09-16）

本次依据 Crawl4AI 对照验证修复 hkl-rec 的来源适配器及质量校验。继续使用现有 API/HTTP 获取流程；浏览器 HTML 已可交给修正后的适配器处理，但未将 Crawl4AI 加入默认 worker 依赖。

## 已修复

- **BBC**：canonical 与最终 URL 身份一致后，允许精确匹配的 HTML title 作为 H1 改写时的备用证据。支持 `layout-block` 中的段落、标题、图文和列表，排除广告、推荐卡片及未知模块；保留封面去重、图片范围和图注。不同文章标题仍拒绝。
- **Guardian**：正文质量按段落、引用和列表条目判断，标题、图注不能凑正文长度；列表型新闻可正常获取。移除交互页 `scroll-tooltip` 和隐藏 `caption-measurer`；sticky caption 只有与同一 horizontal 区域的真实 figure 图注重复时才移除，独有图注和真实重复正文保留。编号数独仍以不支持交互模板处理。
- **Guardian 补图**：只有可重试的 `network_error` 会等待一秒后重试一次。其他错误及最终失败不丢弃 API 正文，写入已有 warnings 字段供详情页展示；服务日志只记录 article_id 和错误码，避免记录鉴权 URL 或异常原文。
- **新华网**：足量的两段正文不再因“三个文本块”门槛失败。200–299 字符的例外只适用于标题精确匹配、请求/最终 URL 主机与路径一致、唯一 `#detail` 容器的中文新闻，并要求至少两个不少于 40 字符的正文片段。正常 300 字符门槛保持默认；图注、标题不能充数。兼容原站不规范 HTML 将 title 放在 body 中的情况。
- **新华网占位图**：排除 `/hnstatics/henanwebsite/detail2023/images/space.gif` 这一已核实的模板装饰。其他路径下同名图片继续保留，同一图片节点的有效 `data-src` 也保留。

提取版本已更新：`bbc-html-2`、`guardian-structured-3`（网页适配器 `guardian-html-2`）、`zh-xinhua-3`。文档 schema_version 仍为 1，数据库无需新增字段或迁移。旧文档仍可读取，已有补抓/版本升级机制可识别新目标版本。

## 真实快照回放

使用此前冻结的 30 个 URL，各自的 HTTP 和浏览器 DOM，共 60 份快照。结果写入新的 `.runtime/news-parser-fix-20260916`，未覆盖原始对照报告。

| 来源 | 静态 HTML 修复前 | 静态 HTML 修复后 | 浏览器 HTML 修复前 | 浏览器 HTML 修复后 |
|---|---:|---:|---:|---:|
| BBC（10 篇） | 8 | 9 | 0 | 9 |
| Guardian（10 篇） | 4 | 5 | 4 | 5 |
| 新华网（10 篇） | 7 | 9 | 7 | 9 |
| 合计 | 19/30 | **23/30** | 11/30 | **23/30** |

这张表只比较 HTML 适配路径，不能与先前包含 Guardian API 的 22/30 直接混用。

所有原先通过的快照均继续通过；有效图片 URL 及顺序保持。排除了原先通过结果中 4 次出现的同一模板占位图（静态/渲染分别计数）。正文变化仅为 Guardian 交互页删除重复图注和滚动提示：18,703 → 16,387 字符，20 张真实图和图注保留，与静态结果一致。

23 对被接受的静态/浏览器快照现在具有相同的正文文本和内容块类型数量。通过程序校验不等于全文视觉复刻，视频、直播和复杂交互仍需要各自的数据来源/展示模型。

仍不接受的 7 个 HTML 样本：1 篇 BBC 页面与库内标题差异较大；Guardian 的 2 个专题列表、2 个直播和 1 个数独；1 篇新华网极短音视频介绍。Guardian 直播可以继续使用原有 API 获取，不把这些页面强行转换成普通 HTML 新闻正文。

## 测试与实网复核

- 新增修复测试采用先失败再修复的流程：BBC、Guardian、新华网复现用例 20 项，另新增精确模板占位图过滤用例。
- 最终全量后端 **654 项通过、1 项跳过、81 项未选中**，结果见 `.runtime/news-parser-fix-20260916/pytest-release.log`；独立 PostgreSQL `_test` 数据库的 BBC 正文流程和 Guardian scope/版本升级用例共 3 项通过。
- Ruff 检查通过；独立审查未发现有证据的 P1/P2 问题，占位图增量另经追加审查和适配器测试。
- 实网只读复核通过：BBC H1 更新案例（8,558 字符）、Guardian 列表正文（4,684 字符）、新华网短新闻（253 字符）及两段新闻（447 字符）。最终实网复测确认这两篇新华网新闻仅含正文，已排除模板占位图。
- 全量首轮的一个真实 Guardian 用例因图片补抓网络错误失败；补充一次有限重试后，真实用例及后续完整回归通过。没有将该网络失败隐藏为跳过。

## 本地运行

正文 worker 与采集服务已重建并更新。容器应运行版本 `bbc-html-2`、`guardian-structured-3`、`zh-xinhua-3`，最终容器镜像为 `sha256:1352845836bcac4557eaffb19b23bae574f555237a45d11cf352b739475b6bef`，两个服务均 running、重启计数 0，容器内占位图过滤断言通过；记录见 `.runtime/news-parser-fix-20260916/deployment.txt`。没有执行历史文章的全量重抓或主动覆盖已有正文；后续抓取使用新版本，历史记录可使用已有定向补抓脚本升级。

保留了回滚镜像标签 `newsrec-worker:before-parser-fix-20260916`。运行时数据库、Kafka 及已有前端未因本次修复重建。

## 文件与复现

- 变更相对本轮开始前的独立 diff：`.runtime/news-parser-fix-20260916/repair.diff`；原文件副本在 `before/`，避免与用户原有未提交改动混淆。
- 逐篇结果：`.runtime/news-parser-fix-20260916/replay-summary.json`。
- 图片、正文顺序一致性检查：`.runtime/news-parser-fix-20260916/replay-checks.json`。
- 实网结果：`.runtime/news-parser-fix-20260916/live-verification.json`。
- 执行计划：`docs/superpowers/plans/2026-09-16-news-parser-repair.md`。

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_live_news_validated_parser_repairs.py tests/test_live_news_html_adapters.py -q --tb=short
.\.venv\Scripts\python.exe .runtime\news-parser-fix-20260916\replay.py
.\.venv\Scripts\python.exe -m pytest tests -q --tb=short
```

快照和实网正文位于本地研究目录，不应发布为公共数据集。实验不是新闻源总体成功率抽样，也未完成全部原站页面的人工视觉验收。
