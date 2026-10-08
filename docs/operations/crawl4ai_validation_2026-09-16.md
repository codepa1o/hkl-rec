# Crawl4AI 与 hkl-rec 新闻内容抓取对照验证

验证日期：2026-09-16。范围：现有 BBC、Guardian、新华网来源。业务代码未修改，数据库只读，未补抓写回、领取任务或重启服务。

## 结论

本次 30 个样本中，Crawl4AI 在一次有限网络重试后全部取得 HTTP 200 页面，但把渲染后的 HTML 直接交给现有适配器，仅 11 篇通过正文校验；现有获取流程为 22 篇。原有 8 个失败样本没有一个因浏览器渲染而通过现有校验。

这证明“直接替换获取方式”当前不可上线，并不证明 Crawl4AI 不适合动态网页。更适合本项目的推进顺序是：先修正已复现的内容类型识别、标题一致性判断、短正文/列表质量校验、补图诊断，再按确有动态内容收益的页面引入浏览器回退。现阶段尚无证据支持为全部来源增加浏览器服务。

## 采样与口径

采用目的性诊断采样，各来源 10 篇：优先近期失败、长正文、多图、近期成功。BBC 普通文章候选中仅 1 篇已存正文、363 篇仅元数据，因此 BBC 实际是 1 篇已存正文和 9 篇元数据样本，不能声称覆盖了 10 篇历史失败。

Guardian 样本包含 2 个专题列表、1 个数独页、2 个直播、2 个交互专题、1 个商品推荐和 2 个普通新闻页面。边界类型保留在结果中，用于暴露上游内容分类问题；这些比例不是新闻源总体分布。新华网覆盖省级子站，包含 3 个失败和 7 个可用正文。

比较的路径：

1. 现有 Provider：Guardian 保留 API 优先及原有回退/补图流程；其他来源使用现有 HTML Provider。
2. 静态 HTML 回放：真实网页快照交给原 HTML 适配器，辅助区分 API 与网页模板差异。
3. 浏览器 HTML 回放：Crawl4AI 访问实际 URL 后，将 `result.html` 交给同一套原 HTML 适配器。
4. 通用提取对照：同时保留整页 Markdown，以及在真实 DOM 上指定正文选择器的离线 Crawl4AI 提取。未使用大模型。

“通过”只表示满足当前程序校验，不等于人工确认全文完整。浏览器结果未写入 `live_news`。原数据库内容只作为参照，不作为绝对正确的标准答案。

## 实测结果

| 来源 | 样本数 | 现有流程通过 | 静态 HTML 适配器通过 | 浏览器取得 HTTP 200 | 浏览器 HTML 接原适配器通过 | 救回原失败 |
|---|---:|---:|---:|---:|---:|---:|
| BBC | 10 | 8 | 8 | 10 | 0 | 0 |
| Guardian | 10 | 7 | 4 | 10 | 4 | 0 |
| 新华网 | 10 | 7 | 7 | 10 | 7 | 0 |
| 合计 | 30 | 22 | 19 | 30 | 11 | 0 |

浏览器首轮为 29/30，一篇 BBC 出现 `ERR_CONNECTION_CLOSED`，重试一次后恢复。正式基线复跑时也有一篇 BBC 网络错误，重试一次后恢复；两边均保存重试前证据，未把瞬时网络错误归类为永久抽取失败。

### BBC：正文没变，渲染后模块标记变了

10/10 篇的正文 `article` 下 `<p>` 文本序列，在压缩空白后与静态 HTML 一致。未观测到浏览器补出额外正文段落。

8 篇原本通过的文章，渲染后变为 `unsupported_template`。已逐层核对 DOM：初始 HTML 使用 `data-component="text-block"`；执行网页脚本后，正文进入 `layout-block` 等布局结构。原 BBC 适配器按模块白名单遍历，因此拒绝这些已渲染页面。该变化发生在 `result.html`，不是 Crawl4AI 的 cleaned_html 清洗造成的。

代表样本 `Ld1c3ff2e486da117055825bb9d9468e4`：原流程 2,175 字符、12 个正文段落、1 张内文图及图注。浏览器正文仍有相同的 12 段，但现有适配器输出失败。

另外 2 篇均在标题校验处失败：

- `Lfdf78be9ceffc19710bb4d842da28033`：库内 Nvidia 标题与当前页面 OpenAI 标题差异较大，须核查元数据/页面更新，不能直接放宽阈值接受。
- `L18fb10f17acb5442775f2a8269d723fd`：库内标题与页面 `<title>` 一致，但 H1 改写，现有只核对 H1 的条件拒绝。适合增加 canonical、HTML title 与 H1 的联合判断。

### Guardian：API、模板和正文类型需要分开处理

现有流程 7 篇通过，而静态 HTML 和浏览器 HTML 路径均只有 4 篇通过。两个直播通过 API 可取得大量正文，但普通文章 HTML 适配器不支持其多条 live block 结构；浏览器不能自动弥补这种模型差异。

`L650615b105af9f6855a62934384c4582` 的 4,684 字符正文实际是 1 个列表、11 个条目，API 流程通过。HTML 适配器仅统计 paragraph 数量/长度，拒绝了这篇有正文的文章。这是质量规则问题，静态和渲染版均能取得该列表。

2 个专题列表和 1 个数独页不应统一按普通新闻正文处理。其失败应优先在内容类型识别和入队策略层解释。

交互文章 `L8efc85aac898fcb6f02ed4c913591462`：同一 HTML 适配器解析静态页面为 16,387 字符、41 段，浏览器页面为 18,703 字符、59 段；增加的 18 段是 6 段滚动提示，以及 6 种图注各重复两次，正文并未因此更完整。两个 HTML 结果都触及 20 张图的处理上限，不能据此认为已保留全部原图。

商品推荐 `Ld493d16aa46e06bf09100eb041109e76`：API 与网页的文本组织及图片补充存在差异，但静态 HTML 与渲染 HTML 的适配结果相同，均为 10,961 字符、20 张图。较 API 更多的图片已经存在于静态页面，无需浏览器才能获取。

另外观测到 API 后的补图结果波动：同一交互文章三次结果分别含 18、0、18 张图。针对性复抓记录确认 API 和 HTML 均可正常返回。由于较早的缺图轮次没有逐跳错误记录，不能确定该次是网络还是解析问题；结合现有代码会忽略补图分支异常，建议补充独立的图片补全状态和失败原因，而不是仅看 `body_status=available`。

### 新华网：7 篇一致，3 篇被质量门槛拒绝

10/10 篇的 `#detail` 内段落文本序列在静态和渲染 HTML 中一致。7 篇通过样本的最终正文、文本块首尾和顺序、图片数量、非空图注数量均一致，没有观察到浏览器带来的结构改善。

3 篇失败的未校验候选分别为 100、253、447 字符。其中 447 字符文章只有 2 个正文段落，被至少 3 个文本块的要求拒绝；另两篇较短，需分别评估是否为有效短新闻或模板遗漏。100 字符候选中包含较短的非正文内容，更不应简单移除长度阈值后入库。

## 通用提取与结构化展示

整页 Markdown 含导航、登录入口、推荐和页脚。增加正文选择器后，26/30 页能产生局部 Markdown；4 页因专题列表/直播不具备唯一普通正文容器而拒绝。26 不等于 26 篇完整正文，其中仍包含数独、短内容和图注重复问题。

BBC 代表样本整页 Markdown 为 11,629 字符，指定 article 后为 3,411 字符，现有正文为 2,175 字符。差额包含标题、署名、链接等，不能当作额外正文。Crawl4AI 的作用是取得 DOM 并辅助提取，仍需本项目定义语义范围、图文顺序和质量条件。

hkl-rec 当前文档模型只支持段落、标题、引用、列表、图片。表格、视频或交互内容的完整展示仍需要独立模型和组件扩展；本实验没有把媒体下载、视频播放或整篇视觉复刻列作通过项。

## 时间与资源

| 来源 | 现有流程耗时中位数 | 浏览器抓取及通用处理中位数 | 该来源观测到的进程树 RSS 峰值 |
|---|---:|---:|---:|
| BBC | 4.61 s | 10.85 s | 720 MiB |
| Guardian | 8.04 s | 9.15 s | 796 MiB |
| 新华网 | 0.29 s | 3.76 s | 695 MiB |

浏览器复用，单页并发 1；按每 250 ms 采样整个实验 Python/浏览器进程树 RSS。峰值包括解释器、SDK 和共享浏览器，不是某个网页独占内存。没有开展 Linux/Docker 压测或长期稳定性测试。

上述时间是操作耗时参考，不是等工作量性能排名：现有 Guardian 路径涉及 API/补图；浏览器路径包括滚动、通用提取，部分还截图，且未包含随后离线执行的原适配器解析时间。两条路径均沿用本机代理，受网络波动影响。正式基线采用项目配置的超时和 2 MiB 响应限制；初轮 8 MiB 实验另存为 `initial_*`，未用于正式表格。

## 推荐推进顺序

1. 优先修正已复现的确定性缺口：普通文章/列表/直播/互动页识别；BBC 标题多证据判断；Guardian 列表正文质量检查；新华网短正文按类型校验。保留明确失败原因。
2. 改善结构层：图片补全状态、图注关联和去重、交互提示排除；原 API 文本保持优先，避免用整页或渲染文本替换。
3. 为 BBC 等建立静态/渲染 DOM 双形态的解析契约，再尝试 Crawl4AI 按来源回退。先用固定 HTML 回归样本验证兼容性。
4. 仅在有证据表明静态 HTML 缺少目标内容时启用浏览器，验收必须包含“新增有效正文/图片且无已有内容退化”。不要把任意 `extraction_quality_failed` 或 `unsupported_template` 都升级成浏览器重试。

## 证据与复现

全部本地证据位于 [`../../.runtime/crawl4ai-validation-20260916`](../../.runtime/crawl4ai-validation-20260916/README.md)。其中 `manifest.json` 为样本清单，`summary.json` 和 `results.csv` 为逐篇结果，`comparison.json` 为对应文章段落对比，`requirements-resolved.txt` 为隔离环境精确依赖，`verification.json` 记录数据库只读和源码哈希。

使用本地 Crawl4AI 0.9.3（仓库提交 `862f6bc`）、Python 3.13.13、Playwright 1.63.0、Chromium Headless Shell 153.0.8010.12。未调用 LLM，未登录网站。基于实际 robots 响应预检，明确 404/410 的缺失规则按 [RFC 9309 §2.3.1.3](https://www.rfc-editor.org/rfc/rfc9309.html#section-2.3.1.3) 处理；无法确认的网络失败不自动放行。

采样不是随机抽样，没有独立的人工全文金标准。已核对异常 DOM、段落差异和部分浏览器截图，截图是滚动结束时的视口，未声称完成全部页面的视觉验收。相关返回快照可能处于不同缓存/更新时间，这是网页/API对比的限制。

## 逐篇结果

单元格数字为最终正文字符数；错误表示原适配器拒绝输出。文章 ID 链接指向本次目标 URL，完整标题和选择理由见 manifest。

| 来源 | 文章 | 原库状态 | 现有流程 | 渲染 HTML 接原适配器 |
|---|---|---|---|---|
| BBC | [Ld1c3ff2e486da117055825bb9d9468e4](https://www.bbc.com/news/articles/cwg7ky12g14jo) | available | 2175 | unsupported_template |
| BBC | [Lfdf78be9ceffc19710bb4d842da28033](https://www.bbc.com/news/articles/cqx2zpj4y525o) | metadata_only | extraction_quality_failed | extraction_quality_failed |
| BBC | [L71dafe6aa3424b6437f8c3c5a1700e57](https://www.bbc.com/news/articles/c6y8zp3kv0x3o) | metadata_only | 4408 | unsupported_template |
| BBC | [L5b948f61f815dd9da8e6974eb9b0ce8b](https://www.bbc.com/news/articles/c8zxz31pdn46o) | metadata_only | 4105 | unsupported_template |
| BBC | [L138ae2b60883c09f72a433e0b4ec8572](https://www.bbc.com/news/articles/cw804154z90ko) | metadata_only | 2115 | unsupported_template |
| BBC | [Lf24ffe5ebaeed79ca81cbc6dd33c233d](https://www.bbc.com/news/articles/crq8j4k99w39o) | metadata_only | 3294 | unsupported_template |
| BBC | [L18fb10f17acb5442775f2a8269d723fd](https://www.bbc.com/news/articles/cz72p75zg4qo) | metadata_only | extraction_quality_failed | extraction_quality_failed |
| BBC | [Ld493c3ffe25810550c34301692c9b201](https://www.bbc.com/news/articles/crgqde1nex2vo) | metadata_only | 3494 | unsupported_template |
| BBC | [L0753065dbaa1cc9a8bed06b592a08fa8](https://www.bbc.com/news/articles/cw1l6zn56e3zo) | metadata_only | 8432 | unsupported_template |
| BBC | [Lbfcaa7216cf41061dc0e5257b062d343](https://www.bbc.com/news/articles/c6zxz18wlg4yo) | metadata_only | 1985 | unsupported_template |
| Guardian | [L09ecd2d2a709b6fcbb4c3bda2481c4e4](https://www.theguardian.com/media/social-media) | failed | invalid_provider_payload | extraction_quality_failed |
| Guardian | [Lfc941192c93094a213842a8f0b4274e7](https://www.theguardian.com/lifeandstyle/2026/sep/16/sudoku-7454-medium) | failed | extraction_quality_failed | extraction_quality_failed |
| Guardian | [Ld766c21a4fbfc70a162ac3a03beb685b](https://www.theguardian.com/us-news/donaldtrump) | failed | invalid_provider_payload | extraction_quality_failed |
| Guardian | [L3d9be6b5d6835d6e05dc2ba604bca0a3](https://www.theguardian.com/australia-news/live/2026/sep/15/one-nation-pauline-hanson-immigration-coalition-andrew-hastie-angus-taylor-labor-anthony-albanese-ntwnfb) | available | 78538 | unsupported_template |
| Guardian | [L6d87261e8dce440d61f1416c865ad6ce](https://www.theguardian.com/us-news/live/2026/aug/18/donald-trump-florida-alaska-wyoming-primaries-midterms-white-house-ballroom-iran-cnn-latest-news-updates) | available | 63347 | extraction_quality_failed |
| Guardian | [L8efc85aac898fcb6f02ed4c913591462](https://www.theguardian.com/environment/ng-interactive/2026/sep/03/plastic-waste-new-york-environment) | available | 12963 | 18703 |
| Guardian | [Ld493d16aa46e06bf09100eb041109e76](https://www.theguardian.com/thefilter/2025/jun/17/best-fans-uk) | available | 11349 | 10961 |
| Guardian | [L650615b105af9f6855a62934384c4582](https://www.theguardian.com/world/2026/sep/16/ukraine-war-briefing-new-anti-drone-weapon-scores-hit-amid-race-against-shahed-jets) | available | 4684 | extraction_quality_failed |
| Guardian | [Leeac57f05aa4ed6af0fabebae8216274](https://www.theguardian.com/us-news/2026/sep/15/russia-us-killings-plot) | available | 3135 | 3135 |
| Guardian | [L5402c61c350132b9649888164bd4da9e](https://www.theguardian.com/world/ng-interactive/2026/sep/16/indonesia-fires-borneo-el-nino-women-haze) | available | 5969 | 5969 |
| 新华网 | [L15eb69a68a70343d3f3f4a092ec1af92](http://www.gs.xinhuanet.com/20260916/52acd50940aa41e9b9e5d44f5faaf0aa/c.html) | failed | extraction_quality_failed | extraction_quality_failed |
| 新华网 | [Lb7edc89e1cf43a8a5b6e6c3228d60625](http://www.ha.xinhuanet.com/20260916/ce0e20be9d874f489feb08c24bfe65c6/c.html) | failed | extraction_quality_failed | extraction_quality_failed |
| 新华网 | [Le99c4ec3150852fb535d6aa5f93adb24](http://www.ha.xinhuanet.com/20260916/f4aa8226b701462887636bbd24235245/c.html) | failed | extraction_quality_failed | extraction_quality_failed |
| 新华网 | [L8caa394655642dd45f18ddfa11dd46d6](http://www.gs.xinhuanet.com/20260916/93468619f1614ad0ba7d09a48984ca18/c.html) | available | 4522 | 4522 |
| 新华网 | [L4039c85b51062ec77d879f9797bd5503](http://www.ha.xinhuanet.com/20260916/c6804e5cbc364d829c1dee59ddc76446/c.html) | available | 3890 | 3890 |
| 新华网 | [Lefc113c06cb16f4020ca16cf25ba6057](http://www.gz.xinhuanet.com/20260910/3ad56ba3451f4ef08daef1d4d4b6378e/c.html) | available | 1321 | 1321 |
| 新华网 | [Le88892aee4d87b688ff20489c7e16179](http://www.hq.xinhuanet.com/20260916/a73da4e276c7478cba2c83f85697439f/c.html) | available | 348 | 348 |
| 新华网 | [L60d6ae347b751304315022e957d07a92](http://www.ha.xinhuanet.com/20260916/9ccf88a4c1bf487e802a817acec38502/c.html) | available | 1240 | 1240 |
| 新华网 | [L61983d321c7e9014e05f6b1c2f75ec12](http://www.gs.xinhuanet.com/20260916/00dc8bacce0e4b0d9d02988eaf2366ce/c.html) | available | 850 | 850 |
| 新华网 | [L0d6bd6fc0802ff4ccaaff450359c3d40](http://www.gs.xinhuanet.com/20260916/87f6e797abd64398b134f96f519a81e6/c.html) | available | 1784 | 1784 |
