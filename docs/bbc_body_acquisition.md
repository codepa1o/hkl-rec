# BBC.com 正文抓取

## 范围

BBC.com 已从 link_only 改为显式启用的本地研究 HTML 来源，适配器及版本为 `bbc` / `bbc-html-1`。仅支持 HTTPS `bbc.com`、`www.bbc.com` 的 `/news/articles/<id>` 普通新闻页面；没有自动扩展 bbc.co.uk、直播或视频页面。无需 API Key、付费抓取服务或浏览器渲染。

必须处于 development 环境且启用 NEWSREC_LOCAL_RESEARCH_FULLTEXT_ENABLED。正文和结构化文档以 local_research 范围保存，生产环境或关闭本地研究模式时不提供正文。

## 抽取方式

抓取前读取 robots.txt 并检查项目抓取标识，遵守可支持的 crawl-delay；请求使用现有 SafeFetcher 的 HTTPS、域名、公共 IP、重定向、超时和大小限制。BBC 页面要求唯一的主 article，标题和 canonical 与目标新闻一致；允许多个完全一致的 canonical 标签，不接受冲突值。

按 data-component 模块白名单保留正文顺序，不依赖散列 CSS 类名。段落、小标题、引用和列表保留；图片模块转换成 figure，去除非正文占位图片，保留真实图片及图注。已有封面不再重复插入正文；图片数量遵守来源配置上限。

署名、发布时间和话题标签单独保存；推荐 links-block、标签列表、页脚、广告以及嵌套的非正文模块不混入正文。未知媒体模块产生原文查看提示。付费访问标记、robots 拒绝、正文容器缺失或质量校验失败都会返回明确错误，不绕过限制、不覆盖已有可用正文。

## 当前文章与补抓

用户指定文章 `Ld1c3ff2e486da117055825bb9d9468e4` 已使用真实网页补抓：2175 字符、12 个正文段落、1 张内文图及图注、2 个话题标签，署名 Gabriela Pomeroy。封面仍沿用原新闻元数据。写回前已备份 article、content_job 和 assets，位置 `.runtime/bbc-repair/`。

单篇预览与写回：

```powershell
python scripts/repair_bbc_content.py --article-id Ld1c3ff2e486da117055825bb9d9468e4
python scripts/repair_bbc_content.py --article-id Ld1c3ff2e486da117055825bb9d9468e4 --apply
```

其他已入库 BBC 新闻可使用现有结构化补抓脚本，先预览再小批执行：

```powershell
python scripts/backfill_live_structured_content.py --source-suffix bbc.com --limit 20 --dry-run
```

没有无差别补抓全部历史 BBC 新闻。新的采集记录会按新来源配置入队。为加载新代码和配置，已重建并更新正文 worker 与新闻采集容器；未主动重启前后端、数据库或 Kafka。

## 验证

BBC 专项回归涵盖真实模块结构、重复 canonical、正文及图注顺序、占位图片过滤、封面去重、嵌套推荐排除、图片数量上限、标签坏链接、访问限制和不支持模板。BBC 与相关抓取/正文测试合计 51 项通过，真实 PostgreSQL 链路 1 项通过，Ruff 通过。

全量后端首轮为 627 项通过、1 项跳过、2 项失败；失败均为已有新华网版本测试仍预期 zh-xinhua-1，而当前独立工作已更新到 zh-xinhua-2，本次未修改那部分测试。未声称全量测试通过。

页面复用既有结构化正文组件，本次无前端功能改动。实际页面视觉验收未完成，交付证据为真实网页获取、数据库/API 回读与自动化测试。
