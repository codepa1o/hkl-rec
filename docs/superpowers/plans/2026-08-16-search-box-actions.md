# 搜索框操作区 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为搜索框增加条件显示的清空按钮和明确的搜索按钮，并在清空时无刷新地重置搜索结果页。

**Architecture:** 保持搜索状态仍由 `SearchBox` 管理，使用 `useLocation()` 判断是否位于搜索页，并通过现有 `navigate()` 完成搜索提交和结果重置。清空操作集中在单一处理函数中，同时重置输入、建议、定时器和焦点；样式继续复用全局主题变量。

**Tech Stack:** React 18、TypeScript、React Router、React Testing Library、Vitest、Lucide React、CSS

---

### Task 1: 用组件测试固定搜索框行为

**Files:**
- Create: `product-frontend/src/components/SearchBox.test.tsx`

- [ ] **Step 1: 编写失败测试**

使用 `MemoryRouter` 渲染真实 `SearchBox`，通过位置探针验证路由，并覆盖：空内容禁用搜索、有内容显示清空按钮、搜索页清空后导航到 `/search` 并保持焦点、首页清空不导航、点击按钮与 Enter 都提交去除首尾空格后的关键词。

```tsx
expect(screen.getByRole("button", { name: "搜索" })).toBeDisabled();
expect(screen.queryByRole("button", { name: "清空搜索内容" })).not.toBeInTheDocument();

fireEvent.change(input, { target: { value: "  climate change  " } });
fireEvent.click(screen.getByRole("button", { name: "搜索" }));
expect(screen.getByTestId("location")).toHaveTextContent("/search?q=climate%20change");

fireEvent.click(screen.getByRole("button", { name: "清空搜索内容" }));
expect(input).toHaveValue("");
expect(input).toHaveFocus();
expect(screen.getByTestId("location")).toHaveTextContent("/search");
```

- [ ] **Step 2: 运行测试并确认 RED**

Run: `npm test -- --run src/components/SearchBox.test.tsx`

Expected: FAIL，因为当前组件没有“清空搜索内容”和“搜索”按钮，也没有清空路由行为。

### Task 2: 实现组合式搜索操作区

**Files:**
- Modify: `product-frontend/src/components/SearchBox.tsx`
- Modify: `product-frontend/src/styles/global.css`
- Modify: `product-frontend/src/components/InterfaceLocalization.test.tsx`

- [ ] **Step 1: 实现最小交互代码**

在 `SearchBox` 中引入 `X`、`useLocation` 和输入框 ref；增加清空处理函数，只有当前路径为 `/search` 时才导航到无查询参数的搜索页。

```tsx
const location = useLocation();
const inputRef = useRef<HTMLInputElement>(null);
const canSearch = query.trim().length > 0;

const handleClear = () => {
  clearTimeout(debounceRef.current);
  setQuery("");
  setSuggestions([]);
  setOpen(false);
  if (location.pathname === "/search") navigate("/search", { replace: true });
  inputRef.current?.focus();
};
```

将“×”按钮放在输入区域内，仅在 `query.length > 0` 时渲染；将“搜索”文字按钮放在控件最右侧，`disabled={!canSearch}`，并继续让 Enter 调用 `handleSubmit()`。

- [ ] **Step 2: 添加聚焦且响应式的样式**

将 `.zr-searchbox` 保持为建议面板定位容器，新增组合容器、清空按钮和搜索按钮样式。搜索按钮使用现有强调色；清空按钮保持低视觉权重；窄屏缩小按钮水平内边距但保留“搜索”文字。

- [ ] **Step 3: 更新中文界面集成断言**

在 `InterfaceLocalization.test.tsx` 中断言顶部搜索框存在中文“搜索”按钮，并验证空输入时处于禁用状态。

- [ ] **Step 4: 运行 GREEN 验证**

Run: `npm test -- --run src/components/SearchBox.test.tsx src/components/InterfaceLocalization.test.tsx`

Expected: PASS。

- [ ] **Step 5: 运行完整前端验证**

Run: `npm test -- --run --exclude src/styles/recentReadingOverflow.test.ts`

Expected: 账号菜单、中文界面、搜索框及其余既有测试全部 PASS。

Run: `npm run build`

Expected: TypeScript 和 Vite 构建成功。

Run: `git diff --check -- product-frontend/src/components/SearchBox.tsx product-frontend/src/components/SearchBox.test.tsx product-frontend/src/components/InterfaceLocalization.test.tsx product-frontend/src/styles/global.css`

Expected: 无空白字符错误。
