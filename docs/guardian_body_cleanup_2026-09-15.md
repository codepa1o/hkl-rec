# Guardian 正文与标签分离修复

## 原因与修复

旧获取流程先读 Guardian API 正文，随后为补图片解析整页 HTML，并用整页解析结果替换 API 正文。因此页尾标签列表、推广等可能被当成正文。现在 API 文本块始终保留；整页只用于补图片，而且必须由相邻、唯一匹配的正文块确定位置。无法可靠确定位置的图片不插入，不用整页文本覆盖正文。

通用解析器排除 footer，仍保留正文中的 ul/ol 和作者说明列表。`StructuredBodyDocument.publisher_tags` 是独立可选元数据（默认空列表），不参与 `derive_body_text`、本地分类或兴趣画像；前端在正文下方显示可换行的胶囊链接。标签链接必须是 HTTPS，拒绝带凭据的链接；Guardian API 元数据还限制 Guardian 域名并按 URL 去重。

标签从官方 API 的 `show-tags=all` 获取，仅采用 keyword/tone 标签，不把 contributor 作者标签当话题。返回字段为 webTitle、webUrl。API 标签集合和顺序可能与官网页尾人工选出的标签有所不同，不承诺逐项复刻官网标签排序。官方文档：https://open-platform.theguardian.com/documentation/search 。沿用已有 NEWSREC_GUARDIAN_API_KEY，没有新账号或付费服务。

## 版本与旧数据

Guardian 的目标抽取版本改为 `guardian-structured-2`，其他新闻源不变；无需数据库迁移，新字段保存在既有 JSON 文档内。修复了 ensure_content_job 的旧版本升级状态：已有合法正文在任务 pending 时保持 body_status=available，避免违反正文非空与状态一致性的数据库约束，直到新正文原子替换。

单篇诊断：

```powershell
python scripts/repair_guardian_content.py --article-id L2a2203f2a92a7182643c7c53aedd2775
```

确认后写回：

```powershell
python scripts/repair_guardian_content.py --article-id L2a2203f2a92a7182643c7c53aedd2775 --apply
```

脚本只接收 Guardian API 文章，先重新获取并校验，再加行锁检查获取期间文章是否变化/是否由其他 worker 处理。覆盖前备份 article、assets、content_job，写回正文、结构化文档、哈希及状态。备份位于 `.runtime/guardian-repair/`，不要提交 Git。首次写回遇到旧状态转换问题，事务已回滚；修复后重试成功。

其他旧 Guardian 文章会在再次入队时按新版本更新。批量历史处理可先预览：

```powershell
python scripts/backfill_live_structured_content.py --source-suffix theguardian.com --since-days 30 --limit 20 --dry-run
```

本次只主动重处理用户指定文章，没有无差别重抓全部历史新闻；批量回填会消耗现有 API 配额。需要逐篇备份时应逐篇使用 repair_guardian_content.py。

## 验证与运行

- 指定文章真实获取成功，14 个正文块、8 个独立标签、5550 字符；正文仅保留作者介绍这一正常列表。该篇没有额外内文图片，封面仍保留。
- 数据库回读确认 body_text 等于从 blocks 派生的文本，正文哈希与文档哈希均一致。
- 旧建筑文章的真实图片回归测试通过，保留至少两张内文图。首次请求因本地代理 TLS EOF 失败，重试后通过；不把网络失败伪报为代码测试通过。
- 新增回归用例验证 API 正文不被推广覆盖、正常列表保留、标签分离/去重/危险 URL 拒绝、元数据异常降级、图片锚点不匹配时不猜位置。
- 前端全量 156 项通过，生产构建通过；真实 Guardian 接口及新用例合计 9 项通过；数据库版本升级及既有 DAO 集成 3 项通过。后端全量首轮 576 项通过，1 个上述远程测试失败后单独重试通过。
- Docker 镜像已重建，live-content-worker 与 live-news-collector 已替换为新代码/配置。未重启前后端、PostgreSQL 或 Kafka。

浏览器桥接权限在此前验证中不可用，本次没有声称完成登录页面视觉验收；页面展示通过组件测试验证。测试失败时使用 `--tb=short`，避免公开包含鉴权参数的详细调用栈。
