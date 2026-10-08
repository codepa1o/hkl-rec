# Guardian API → 网页备用获取（本地研究）

## 范围与开关

本次仅支持 Guardian 普通文章的公开 HTML，不使用付费抓取服务或浏览器渲染。API 仍优先，只有明确 API tier restriction、成功响应缺少正文或正文过短时，才尝试网页。普通 401/403、404、429、5xx 和网络错误不会直接切换网页：鉴权错误明确提示，临时错误沿用后台有限重试。

启用需要同时满足：

- 全局 `NEWSREC_GUARDIAN_HTML_FALLBACK_ENABLED=1`；默认关闭，本机已启用。
- Guardian 来源配置 `content.html_fallback_enabled=true`。
- `NEWSREC_ENVIRONMENT=development` 且 `NEWSREC_LOCAL_RESEARCH_FULLTEXT_ENABLED=1`。
- 已配置 Guardian API Key，允许先校验主通道结果。没有 Key 不自动启用纯网页模式。

网页访问遵守 robots.txt；不注入登录 Cookie、不破解验证码、不绕过付费墙或访问拦截。robots 获取失败会停止当前网页尝试。来源可抓取不等同于内容可以公开转载，本实现将其限定为本地研究数据。

## 抽取与展示

网页请求沿用 SafeFetcher，限制 HTTPS、来源域名、重定向、公共 IP、响应大小和超时。robots 缓存一小时；同一 provider 的网页请求至少间隔一秒，尊重可支持的 crawl-delay。

Guardian 适配器要求唯一 `.article-body-commercial-selector` 正文容器；核对 canonical、最终 URL 和页面标题，不退化为全页文字抽取。识别明确的付费访问标记，空白/损坏 HTML 转换成可处理的失败，不终止整个 worker。

保留正文段落、小标题、引文、列表、配图及图片说明的顺序；排除正文外的导航、页尾标签、侧栏和已识别推荐模块。原站话题标签独立存入 publisher_tags。署名优先采用页面可见的 meta-byline，避免通用 JSON-LD 作者覆盖实际署名。表格、视频、iframe 等当前不支持内容会生成提示，不能宣称它们被完整复刻。

结构化文档继续使用兼容的 `guardian-structured-2`，HTML 适配器单独记录 `html_adapter_version=guardian-html-1`。实际来源为 `body_source=html`，`fallback_reason` 保存 API 未提供正文的原因；更新时同步正文及文档哈希。页面显示“本地研究正文”“来源：原站网页”和不支持内容提示。

后台失败保留 API 与网页错误代码，不向前端暴露详细网络栈或鉴权 URL。详情页区分访问受限、结构不支持、网络重试及普通失败；轮询达到上限后提示后台仍在处理，不能无限显示正在获取。

## 数据安全与历史修复

网页结果强制 `body_access_scope=local_research`。正常重新采集、切换为 link_only 后再恢复，均不能将保留的网页文档改成 public。生产环境或关闭本地研究模式后，正文文本和结构化文档都不返回。抓取失败不会覆盖之前合法的正文。

单篇先预览、再备份写回：

```powershell
python scripts/repair_guardian_content.py --article-id L09b6972bcf8f70360e454aca877c2f9c
python scripts/repair_guardian_content.py --article-id L09b6972bcf8f70360e454aca877c2f9c --apply
```

历史受限任务小批处理：

```powershell
python scripts/backfill_guardian_html.py --since-days 7 --limit 5
python scripts/backfill_guardian_html.py --since-days 7 --limit 2 --apply
```

批量上限 20，默认仅列出候选、不写库。旧 authentication_required/403 只是待诊断候选，每篇必须重新请求 API 并确认具体原因，不能通过批量改状态绕过检查。每篇写回前在 `.runtime/guardian-repair/` 备份 article、assets、content_job，并检查并发修改。没有修改用户互动、画像或分类数据。失败仍保留旧数据，可在网络恢复后明确重试。

## 部署与验证记录

本机 `.env` 已启用开关，Docker compose 透传给正文 worker。更新了 live-content-worker 和 live-news-collector 镜像及容器，未重启前后端、数据库或 Kafka。前端修改已通过生产构建，API 新增字段沿用现有热加载。

2026-09-16 已验证用户指定新闻可通过公开网页得到 14 个正文段落、6 个标签、2969 字符，旧数据已备份写回；另外两篇历史受限新闻也通过同一链路处理，其中一篇长文有 114 个内容块和 5 张内文图。真实接口回读确认本地模式可见、生产模式隐藏。网络请求曾出现可重试的 network_error，未将失败结果覆盖到正文。

回归覆盖：精确 tier 403 分类、主通道失败类型、按来源退出、正文缺失、robots 拒绝、canonical/标题不匹配、付费标记、未知模板、空白 HTML、正常正文结构、标签分离、署名优先级、scope 持久性和轮询上限。

已有浏览器桥接权限限制尚未解除；本次页面验证以组件测试、构建和 API/数据库回读为证据，不宣称完成登录页面的视觉验收。

最终回归：后端非远程全量 597 项通过（另 1 项远程用例未启用，数据库标记用例默认排除）；前端全量 159 项通过，生产构建通过；数据库 scope/版本转换与既有 DAO 定向 4 项通过。既有依赖弃用提示保留，不影响这些结果。真实目标网页已通过实际请求验证，且回读正文哈希、文档哈希均匹配。

独立审查推动修复了两项边界：link_only→Guardian 配置转换不能把保留的本地文档公开；空白 HTML 必须转换成可处理的抓取错误。另通过实际页面核对，修正了 JSON-LD 默认作者与页面可见 Reuters 署名不一致的问题。
