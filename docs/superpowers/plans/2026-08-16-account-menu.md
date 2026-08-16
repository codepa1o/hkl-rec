# 顶部账号菜单 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将顶部重复的账号名称、退出按钮和推荐画像切换器合并为一个可访问、响应式的账号菜单。

**Architecture:** 新建 `AccountMenu` 作为账号与推荐画像的唯一入口，由它组合 `useAuth()` 和 `usePersona()` 的现有数据与操作。`TopNav` 只保留主题切换和账号菜单；交互状态封装在新组件内，视觉样式继续使用全局设计变量。

**Tech Stack:** React 18、TypeScript、React Testing Library、Vitest、Lucide React、CSS

---

### Task 1: 用组件测试固定账号菜单行为

**Files:**
- Create: `product-frontend/src/components/AccountMenu.test.tsx`

- [ ] **Step 1: 写失败测试**

创建可变的 Auth/Persona mock，验证默认态只显示一次账号姓名；点击后显示邮箱、“推荐画像”、“我的画像”、其他画像、“当前”和“退出登录”；选择画像调用 `selectPersona`；按 Escape 关闭菜单；点击退出调用 `logout`。

```tsx
expect(screen.getAllByText("胡科浪")).toHaveLength(1);
await user.click(screen.getByRole("button", { name: "打开账号菜单" }));
expect(screen.getByText("hukelang@example.com")).toBeInTheDocument();
expect(screen.getByText("我的画像")).toBeInTheDocument();
expect(screen.getByText("体育读者")).toBeInTheDocument();
expect(screen.getByText("当前")).toBeInTheDocument();
```

- [ ] **Step 2: 运行测试并确认失败**

Run: `npm test -- --run src/components/AccountMenu.test.tsx`

Expected: FAIL，因为 `AccountMenu.tsx` 尚不存在。

### Task 2: 实现独立账号菜单

**Files:**
- Create: `product-frontend/src/components/AccountMenu.tsx`
- Delete: `product-frontend/src/components/PersonaSwitcher.tsx`

- [ ] **Step 1: 实现触发器和菜单结构**

组件读取 `user`、`logout`、`personas`、`selectedPersona`、`selectPersona` 与 `loading`。账号首字作为头像；账号本人画像显示“我的画像”，其他画像通过 `localizePersonaName()` 显示。

```tsx
const personaLabel = (userId: number, displayName: string) =>
  userId === user?.user_id ? "我的画像" : localizePersonaName(displayName);
```

- [ ] **Step 2: 实现关闭与操作行为**

添加外部 `mousedown`、全局 `keydown` Escape 监听；画像选择后关闭；退出期间禁用按钮，失败时显示“退出失败，请稍后重试”。

```tsx
const handleSelectPersona = (userId: number) => {
  selectPersona(userId);
  setOpen(false);
};
```

- [ ] **Step 3: 运行账号菜单测试**

Run: `npm test -- --run src/components/AccountMenu.test.tsx`

Expected: PASS。

### Task 3: 接入顶部导航并完成视觉样式

**Files:**
- Modify: `product-frontend/src/components/TopNav.tsx`
- Modify: `product-frontend/src/styles/global.css`
- Modify: `product-frontend/src/components/InterfaceLocalization.test.tsx`

- [ ] **Step 1: 简化 TopNav**

移除 `useAuth`、`LogOut`、独立账号文本和 `PersonaSwitcher`，改为渲染 `AccountMenu`。

```tsx
<div className="zr-topbar__actions">
  <button className="zr-icon-button" onClick={toggleTheme}>{/* theme icon */}</button>
  <AccountMenu />
</div>
```

- [ ] **Step 2: 添加账号菜单样式**

实现 42px 账号胶囊、30px 头像、286px 下拉菜单、账号头部、画像活动态、底部退出区和错误态；在 `@media (max-width: 560px)` 中隐藏姓名及箭头。

- [ ] **Step 3: 更新界面集成测试**

将 Persona mock 改为已加载的账号本人和体育画像，断言顶部只出现一次登录姓名且不存在独立“退出登录”图标按钮；打开账号菜单后再断言菜单中文结构。

- [ ] **Step 4: 运行前端全量验证**

Run: `npm test -- --run`

Expected: 全部测试 PASS。

Run: `npm run build`

Expected: TypeScript 和 Vite 构建成功。

Run: `git diff --check`

Expected: 无空白符错误。
