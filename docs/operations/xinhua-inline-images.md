# 新华网正文图片与图注

## 实现

- 新华网解析版本为 `zh-xinhua-2`，保留段落内图片及文字先后顺序，支持独立 img、嵌套 span、picture 和懒加载地址。
- 新华网适配器将有明确来源图注特征的相邻段落归入 `ImageBlock.caption`；图片下显示图注，署名保留，不在正文重复。
- 不复制原站广告、导航和任意 HTML/CSS。正文首行缩进保持不变，图注不缩进，字号 1rem、行高 1.6。
- 图片数量服从来源配置，默认最多 20 张；超过限制不影响正文文字。

## 本地研究图片加载

部分新华网图片原地址是 HTTP，但同路径 HTTPS 证书无效，因此不能简单把 http 替换成 https。

这类图片保留真实 `source_url`，使用以下后端地址展示：

```text
GET /articles/live/{article_id}/assets/{asset_id}
```

前端根据现有 `VITE_NEWSREC_API_BASE` 解析这个后端相对路径。正常 HTTPS 图片仍沿用原有展示方式。

接口沿用登录校验，并要求同时满足：development 环境、本地研究开关开启、文章及来源均为 local_research、来源允许全文及图片。服务端从数据库获取 URL，核对文章、当前结构化文档和资源关联，不接受任意 URL 参数。

图片获取有域名白名单、公网 IP 校验、连接 IP 固定、重定向限制、4 路并发限制、读取期限和最多 8 MiB 大小限制。仅允许经 Pillow 验证的 PNG/JPEG/GIF/WebP，按真实图片格式发送，不信任扩展名。没有关闭 TLS 证书校验。

响应使用 `private, no-store` 和 `nosniff`，不创建持久化图片缓存。图片失败时页面保留图注和占位提示。生产环境、研究开关关闭、来源被禁用或文章被阻止后不能访问研究图片。

后端依赖新增 `Pillow>=11.3,<13`，安装后端依赖时自动带上；正文 worker 本身不负责图片二进制下载，不需要新增 Pillow 依赖。

## 部署与回填

更新前端及后端代码；运行中的 `uvicorn --reload` 会加载新路由。若未开启热更新，需要重启后端。

采集器在启动时缓存来源配置，版本升级时应与正文 worker 一起重新加载：

```powershell
docker compose build live-content-worker
docker compose up -d --no-deps live-content-worker live-news-collector
```

先预览单篇修复，再执行：

```powershell
python scripts/backfill_live_structured_content.py --article-id L2ef0d15b167a284fdac5efa63c19782b --source-suffix xinhuanet.com --language zh --since-days 30 --limit 1 --dry-run
python scripts/backfill_live_structured_content.py --article-id L2ef0d15b167a284fdac5efa63c19782b --source-suffix xinhuanet.com --language zh --since-days 30 --limit 1
```

旧新闻分批升级（确认 dry-run 数量后去掉 `--dry-run`）：

```powershell
python scripts/backfill_live_structured_content.py --source-suffix xinhuanet.com --language zh --since-days 30 --limit 100 --dry-run
```

回填在 LIMIT 前排除最新版，排除 fetching/blocked 任务和已经尝试当前目标版本但失败的任务，避免重复刷同一批记录。质量失败的文章应先分析原因，不反复重置状态。升级期间不删除旧正文，新 document 与资源仍使用原有事务写入。

不是每篇新闻都含有图片；无法确定的相邻段落仍作为正文保留，不强制判定为图注。其他中文来源可以使用通用图片解析，但来源特有图注规则与旧数据升级需分别验证，不能把新华网规则直接套在所有站点上。

## 2026-09-16 验证记录

- 示例 `L2ef0d15b167a284fdac5efa63c19782b` 已升级；文档顺序为 image、paragraph、paragraph、image、paragraph，2 条图片资源记录。
- 两张图片经真实数据库读取与中转获取成功，均验证为 PNG，分别为 848,567 和 867,338 字节，均有图注。
- 未登录访问运行中后端的图片接口得到 401；运行中的 OpenAPI 已包含新路由。组件测试验证前端正确解析后端路径及图注展示。
- 示例加小批回填共 21 篇：19 篇完成，2 篇 `extraction_quality_failed`，没有放宽质量门槛。
- 批次完成时 dry-run 仍有 1,635 篇历史候选；未启动全量回填。
- 本轮后端相关回归 110 passed、1 skipped、5 deselected；前端相关回归 16 passed；前端构建成功；相关 Ruff 检查及 4 个核心模块 Mypy 检查通过。
- 浏览器自动化连接不可用，未完成登录状态下的实际视觉验收；不能将组件测试等同于浏览器截图验证。

本方案仅保持既有本机、论文与非公开演示边界，不代表取得图片公开再分发许可。
