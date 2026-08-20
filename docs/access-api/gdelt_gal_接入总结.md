# GDELT Global Aggregation of the Latest 接入总结

## 基本信息

- 提供商：GDELT Project
- 数据源：Global Aggregation of the Latest（GAL）
- RSS 入口：`https://storage.googleapis.com/data.gdeltproject.org/gdeltv3/gal/feed.rss`
- 批次入口：`https://storage.googleapis.com/data.gdeltproject.org/gdeltv3/gal/{timestamp}.gal.json.gz`
- 认证方式：公开端点，无需 API Key
- 调用模式：RSS 发现最新批次，HTTPS GET 拉取 gzip JSONL

## 项目实现

| 功能 | 位置 | 状态 |
|---|---|---|
| RSS 最新批次解析 | `backend/app/live_news/collector.py` | 已实现 |
| gzip GAL 拉取与恢复扫描 | `backend/app/live_news/collector.py` | 已实现 |
| 白名单、中文/英文过滤与规范化 | `backend/app/live_news/normalize.py` | 已实现 |
| PostgreSQL 批次审计与 checkpoint | `backend/app/live_news/dao.py` | 已实现 |
| 有界真实端点连通性检查 | `scripts/check_gdelt_connectivity.py` | 已实现 |

采集仅保存标题、摘要、图片 URL、发布者、语言、时间、来源域名和原文链接，不保存或转载
文章正文。失败批次不会推进持久化 checkpoint。

## 资源与运行

无需凭证。运行前只需配置 PostgreSQL，并执行最新 Alembic 迁移：

```bash
python -m alembic upgrade head
python scripts/check_gdelt_connectivity.py --timeout-seconds 10
python scripts/run_live_news_collector.py --once
```

## 测试报告

- 离线契约测试：`tests/test_check_gdelt_connectivity.py`
- 采集流程测试：`tests/test_live_news_collector.py`
- 真实冒烟：2026-08-18 使用 10 秒超时成功读取 RSS，返回
  `lastBuildDate=2026-08-18T02:17:00+00:00`
- CI：真实连通性检查设为 `continue-on-error`，上游不可用不会破坏确定性门禁

边界保护包括 RSS 根节点、`channel`、`lastBuildDate`、最大 1 MB 响应和 1–60 秒超时检查。
