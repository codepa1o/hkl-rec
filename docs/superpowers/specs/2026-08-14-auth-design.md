# NewsIntentRec 登录注册鉴权设计

## 背景与选择

项目是 FastAPI + React 18 + TypeScript + Vite + MySQL 的新闻推荐演示系统。现有 `app_user` 只承载推荐画像身份，没有邮箱、密码或会话；前端已有 React Router、深浅色主题和一套紫色强调的内容产品视觉。

本次参考 GitHub 候选中的 TOP1 `fastapi/full-stack-fastapi-template`。它与本项目技术栈重合度最高，并提供成熟的 Argon2 密码哈希、JWT、当前用户依赖、登录/注册表单、受保护路由、Pytest 和前端端到端测试模式。实现不搬入其 SQLModel/PostgreSQL/TanStack/Tailwind 基础设施，而是将这些模式适配为现有 PyMySQL、Pydantic、React Router 和原生 CSS 架构。

## 目标与非目标

目标：

- 用户可用邮箱、显示名称和密码注册，并自动获得一个与账号一一绑定的冷启动推荐画像。
- 用户可登录、刷新页面恢复会话、访问受保护界面并退出。
- 密码只保存 Argon2 哈希；登录失败统一返回相同错误，避免泄露账号是否存在。
- 会话保存在 `HttpOnly`、`SameSite=Lax` Cookie 中，前端 JavaScript 不接触令牌。
- 登录和注册界面适配现有深浅色主题、响应式布局和中文产品语气。

非目标：

- 本期不实现第三方 OAuth、邮箱验证、找回密码、RBAC、MFA 或分布式登录限流。
- 配置鉴权密钥后，推荐、搜索、事件、文章与画像 API 都要求有效会话；未配置时默认拒绝业务 API，只有显式开启 `NEWSREC_ALLOW_UNAUTHENTICATED_RESEARCH_API=1` 才保留原有离线研究测试模式。研究演示用的 persona 切换能力保留，但只放行数据库标记的演示用户；登录账号绑定的画像位于首位并默认选中。

## 架构

### 后端

新增独立的 `AuthRepository` 边界和 MySQL 实现，避免继续膨胀现有 `MysqlRuntimeRepository`。`user_account` 保存规范化邮箱、密码哈希、启用状态和时间戳，并通过唯一 `user_id` 外键绑定 `app_user`。为避免改动已被多张表外键引用的主键，注册用户 ID 由事务内加锁的 `auth_user_id_sequence` 分配，同时继续允许导入器显式写入 MIND 演示 ID。

注册在一个事务内完成：插入 `app_user` 获得 ID，插入 `user_account`，再从默认冷启动种子创建 `user_profile`。任一步失败均回滚。

`AuthService` 负责注册、验证密码、签发短期 JWT 和解析当前用户。HTTP 路由只处理 Cookie 与状态码：

- `POST /auth/register`
- `POST /auth/login`
- `GET /auth/me`
- `POST /auth/logout`

JWT 使用 HS256，密钥必须由 `NEWSREC_AUTH_SECRET_KEY` 提供且至少 32 个字符。Cookie 名称、过期时间和生产环境 `Secure` 开关可配置。

### 前端

`AuthProvider` 在应用启动时请求 `/auth/me` 恢复会话，向组件暴露 `user`、`loading`、`login`、`register` 和 `logout`。API 客户端所有请求启用 `credentials: include`。

路由分成公开 `/auth` 和受保护产品壳。未登录访问产品页面时跳转 `/auth`；已登录访问 `/auth` 时回到首页。产品壳内部继续保留现有 `PersonaProvider`，避免认证恢复期间触发受保护区域的数据请求。

登录注册页采用克制的编辑式双栏布局：左侧用大标题和简短价值主张建立产品感，右侧是清晰的表单；小屏合并为单栏。颜色、边框、面板和文本全部复用现有 CSS 变量，不新增 UI 框架。

## 校验与错误处理

- 邮箱在服务端去除首尾空格并转小写，使用可靠的邮箱校验器验证。
- 显示名称长度为 2–40；密码长度为 8–128，允许密码管理器生成的任意复杂密码，不强制脆弱的字符组合规则。
- 重复邮箱返回 409；错误邮箱或密码统一返回 401 和“邮箱或密码错误”。
- 缺失、篡改或过期 Cookie 返回 401；前端清空用户状态并跳转登录页。
- 数据库未配置、鉴权密钥缺失或冷启动种子缺失时返回明确的 503 配置错误，不使用不安全默认密钥。

## 测试策略

- 后端单元测试：Argon2 不保存明文、JWT 正常/篡改/过期、注册规范化、重复账号、错误密码。
- 后端路由模拟：注册设置 HttpOnly Cookie、`/auth/me` 恢复、错误登录、退出清 Cookie、无会话被拒绝。
- 前端组件测试：恢复会话、登录注册切换、错误展示、受保护路由跳转、退出。
- 回归验证：鉴权专项 Pytest、排除本机缺失 FAISS 的后端全量回归、Vitest 全量、TypeScript/Vite 生产构建。

## 安全说明

Cookie 采用 `HttpOnly`、`SameSite=Lax`；`NEWSREC_ENVIRONMENT=production` 时服务强制要求 `NEWSREC_AUTH_COOKIE_SECURE=1` 并通过 HTTPS 提供服务。浏览器状态变更请求校验允许的 Origin，登录和注册按客户端限流。JWT 仅包含用户 ID、签发与过期时间，不包含密码或画像数据。短期令牌退出时从浏览器删除；服务端强制检查账号仍处于启用状态。业务接口只允许操作当前账号，或数据库明确标记为 `is_demo_user=1` 的研究演示人格，避免跨账号越权。
