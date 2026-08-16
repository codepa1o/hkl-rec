# Cinematic Authentication Motion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the approved cinematic option C for the React authentication page, including curtain transitions, state-driven feedback, responsive layout, reduced-motion behavior, and delayed success navigation.

**Architecture:** Keep authentication requests and controlled fields in `AuthPage`, and move cinematic presentation into a focused `AuthCinematicStage` component. `AuthPage` owns a small `AuthPhase` state machine and cleaned-up timers; Motion renders short state transitions while CSS owns the static composition and responsive layout.

**Tech Stack:** React 18, TypeScript 5.6, Vite 5, Motion for React, Vitest, Testing Library, CSS custom properties.

---

## File map and ownership

- Create `product-frontend/src/components/AuthCinematicStage.tsx`: cinematic story copy, curtain layers, Motion variants, success overlay, and presentational phase types.
- Create `product-frontend/src/components/AuthCinematicStage.test.tsx`: presentation and accessibility contract tests.
- Modify `product-frontend/src/pages/AuthPage.tsx`: form state, phase state machine, transition timing, focus transfer, request handling, and navigation.
- Modify `product-frontend/src/pages/AuthPage.test.tsx`: mode transition, request feedback, success delay, initial-session redirect, and reduced-motion tests.
- Modify `product-frontend/src/styles/global.css`: replace the authentication block and its responsive rules with the approved cinematic layout.
- Modify `product-frontend/package.json` and `product-frontend/package-lock.json`: add `motion`.

`AuthPage.tsx` and `global.css` already contain user-owned uncommitted work. Keep edits scoped to authentication code and do not stage or commit these overlapping files automatically.

### Task 1: Add Motion and the isolated cinematic stage

**Files:**
- Modify: `product-frontend/package.json`
- Modify: `product-frontend/package-lock.json`
- Create: `product-frontend/src/components/AuthCinematicStage.test.tsx`
- Create: `product-frontend/src/components/AuthCinematicStage.tsx`

- [ ] **Step 1: Install the animation dependency**

Run:

```powershell
cd product-frontend
npm install motion
```

Expected: `motion` appears in dependencies and npm updates the lockfile without changing unrelated dependency versions.

- [ ] **Step 2: Write the failing presentation tests**

Create `AuthCinematicStage.test.tsx` with these contracts:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import AuthCinematicStage from "./AuthCinematicStage";

describe("AuthCinematicStage", () => {
  it("renders login story and exposes the active phase", () => {
    render(
      <AuthCinematicStage mode="login" phase="idle" reducedMotion={false}>
        <span>表单内容</span>
      </AuthCinematicStage>,
    );

    expect(screen.getByTestId("auth-stage")).toHaveAttribute("data-phase", "idle");
    expect(screen.getByRole("heading", { name: "继续你的阅读脉络" })).toBeInTheDocument();
    expect(screen.getByText("表单内容")).toBeInTheDocument();
  });

  it("renders the registration story and success status", () => {
    render(
      <AuthCinematicStage mode="register" phase="success" reducedMotion={true}>
        <span>注册表单</span>
      </AuthCinematicStage>,
    );

    expect(screen.getByRole("heading", { name: "建立你的阅读坐标" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("阅读世界正在展开");
  });
});
```

- [ ] **Step 3: Run the test to verify red state**

Run:

```powershell
npm test -- src/components/AuthCinematicStage.test.tsx
```

Expected: FAIL because `AuthCinematicStage.tsx` does not exist.

- [ ] **Step 4: Implement the presentational component**

Create the component with exported types and a fixed copy table:

```tsx
import { AnimatePresence, motion } from "motion/react";
import type { ReactNode } from "react";

export type AuthMode = "login" | "register";
export type AuthPhase =
  | "entering"
  | "idle"
  | "switching"
  | "submitting"
  | "error"
  | "success";

interface AuthCinematicStageProps {
  mode: AuthMode;
  phase: AuthPhase;
  reducedMotion: boolean;
  children: ReactNode;
}

const COPY = {
  login: {
    eyebrow: "NEWS · INTENT · CONTEXT",
    title: ["继续你的", "阅读脉络"],
    body: "让每一次搜索、停留与选择，逐渐形成真正属于你的新闻视野。",
    note: "你的兴趣会变化，推荐也应当如此。",
  },
  register: {
    eyebrow: "YOUR READING PROFILE",
    title: ["建立你的", "阅读坐标"],
    body: "从第一次选择开始，让兴趣、语境与时间共同塑造你的阅读档案。",
    note: "每一次选择，都是阅读世界的新坐标。",
  },
} as const;

const cinematicEase = [0.77, 0, 0.18, 1] as const;

export default function AuthCinematicStage({
  mode,
  phase,
  reducedMotion,
  children,
}: AuthCinematicStageProps) {
  const copy = COPY[mode];
  const isSwitching = phase === "switching";
  const isSuccess = phase === "success";
  const curtainAnimation = reducedMotion
    ? { opacity: 1 }
    : isSuccess
      ? { x: "-44%", scaleX: 4.9, rotate: 0 }
      : isSwitching
        ? { x: ["0%", "-44%", "0%"], scaleX: [1, 4.9, 1], rotate: [-8, 0, -8] }
        : phase === "submitting"
          ? { x: "-3%", scaleX: 1.08, rotate: -8 }
          : { x: "0%", scaleX: 1, rotate: -8 };
  const curtainTransition = reducedMotion
    ? { duration: 0 }
    : { duration: isSuccess ? 0.68 : isSwitching ? 0.7 : 0.55, ease: cinematicEase };
  const contentMotion = reducedMotion
    ? { initial: false as const, animate: { opacity: 1 }, exit: { opacity: 1 } }
    : {
        initial: { opacity: 0, y: 24, filter: "blur(8px)" },
        animate: { opacity: 1, y: 0, filter: "blur(0px)" },
        exit: { opacity: 0, y: -18, filter: "blur(7px)" },
      };

  return (
    <main
      className="zr-auth-page"
      data-mode={mode}
      data-phase={phase}
      data-testid="auth-stage"
    >
      <div aria-hidden="true" className="zr-auth-grain" />
      <motion.div
        aria-hidden="true"
        animate={curtainAnimation}
        className="zr-auth-curtain zr-auth-curtain--back"
        initial={reducedMotion ? false : { x: "-150%", rotate: -8 }}
        transition={{ ...curtainTransition, delay: reducedMotion ? 0 : 0.04 }}
      />
      <motion.div
        aria-hidden="true"
        animate={curtainAnimation}
        className="zr-auth-curtain"
        initial={reducedMotion ? false : { x: "-165%", rotate: -8 }}
        transition={curtainTransition}
      />

      <a className="zr-auth-brand" href="/" aria-label="新闻意图推荐">
        <span className="zr-auth-brand__mark">N</span>
        <span>新闻意图推荐</span>
      </a>

      <section className="zr-auth-story" aria-label="产品介绍">
        <AnimatePresence mode="wait">
          <motion.div
            key={mode}
            {...contentMotion}
            className="zr-auth-story__copy"
            transition={{ duration: reducedMotion ? 0.1 : 0.42, ease: cinematicEase }}
          >
            <p className="zr-auth-eyebrow">{copy.eyebrow}</p>
            <h1><span>{copy.title[0]}</span><span>{copy.title[1]}</span></h1>
            <p>{copy.body}</p>
          </motion.div>
        </AnimatePresence>
        <p className="zr-auth-story__note">{copy.note}</p>
      </section>

      <section className="zr-auth-panel">
        <AnimatePresence mode="wait">
          <motion.div
            key={mode}
            {...contentMotion}
            animate={
              phase === "error" && !reducedMotion
                ? { opacity: 1, x: [0, -4, 4, 0], filter: "blur(0px)" }
                : contentMotion.animate
            }
            className="zr-auth-form-wrap"
            transition={{ duration: phase === "error" ? 0.24 : reducedMotion ? 0.1 : 0.42 }}
          >
            {children}
          </motion.div>
        </AnimatePresence>
      </section>

      <AnimatePresence>
        {isSuccess && (
          <motion.div
            className="zr-auth-success"
            initial={reducedMotion ? false : { clipPath: "inset(0 100% 0 0)" }}
            animate={{ clipPath: "inset(0 0 0 0)" }}
            exit={{ opacity: 0 }}
            transition={{ duration: reducedMotion ? 0 : 0.68, ease: cinematicEase }}
          >
            <p role="status"><strong>阅读世界正在展开</strong><span>正在进入你的个性化信息流…</span></p>
          </motion.div>
        )}
      </AnimatePresence>
    </main>
  );
}
```

- [ ] **Step 5: Run the component test to verify green state**

Run:

```powershell
npm test -- src/components/AuthCinematicStage.test.tsx
```

Expected: 2 tests PASS.

### Task 2: Add the authentication phase state machine

**Files:**
- Modify: `product-frontend/src/pages/AuthPage.test.tsx`
- Modify: `product-frontend/src/pages/AuthPage.tsx`

- [ ] **Step 1: Extend tests for transitions and navigation**

Mock reduced motion with mutable hoisted state, import `act` from Testing Library, keep existing form assertions, and add these cases:

```tsx
const motionPreference = vi.hoisted(() => ({ reduced: true }));

vi.mock("motion/react", async (importOriginal) => ({
  ...(await importOriginal<typeof import("motion/react")>()),
  useReducedMotion: () => motionPreference.reduced,
}));

it("切换注册后更新场景并聚焦显示名称", async () => {
  renderPage();
  fireEvent.click(screen.getByRole("button", { name: "创建账号" }));
  expect(await screen.findByRole("heading", { name: "建立你的阅读坐标" })).toBeInTheDocument();
  expect(screen.getByLabelText("显示名称")).toHaveFocus();
});

it("本次登录成功后播放成功阶段再返回原位置", async () => {
  vi.useFakeTimers();
  motionPreference.reduced = false;
  authState.login.mockImplementation(async () => {
    authState.user = { user_id: 7004, email: "reader@example.com", display_name: "新闻读者" };
  });
  renderPage([{ pathname: "/auth", state: { from: { pathname: "/search" } } }]);
  fireEvent.change(screen.getByLabelText("邮箱"), { target: { value: "reader@example.com" } });
  fireEvent.change(screen.getByLabelText("密码"), { target: { value: "news-password" } });
  fireEvent.submit(screen.getByRole("button", { name: "登录" }).closest("form")!);
  await act(async () => { await Promise.resolve(); });
  expect(screen.getByRole("status")).toHaveTextContent("阅读世界正在展开");
  expect(screen.queryByText("目标页面")).not.toBeInTheDocument();
  act(() => vi.advanceTimersByTime(680));
  expect(screen.getByText("目标页面")).toBeInTheDocument();
  vi.useRealTimers();
});

it("减少动态时成功后立即导航", async () => {
  motionPreference.reduced = true;
  authState.login.mockImplementation(async () => {
    authState.user = { user_id: 7004, email: "reader@example.com", display_name: "新闻读者" };
  });
  renderPage();
  fireEvent.change(screen.getByLabelText("邮箱"), { target: { value: "reader@example.com" } });
  fireEvent.change(screen.getByLabelText("密码"), { target: { value: "news-password" } });
  fireEvent.submit(screen.getByRole("button", { name: "登录" }).closest("form")!);
  expect(await screen.findByText("目标页面")).toBeInTheDocument();
});
```

Reset `motionPreference.reduced`, timer mode, and `authState.user` in `beforeEach`/`afterEach` so tests cannot leak state.

- [ ] **Step 2: Run page tests to verify red state**

Run:

```powershell
npm test -- src/pages/AuthPage.test.tsx
```

Expected: new tests FAIL because switching is immediate and no success phase exists.

- [ ] **Step 3: Implement deterministic phase and timer handling**

Update `AuthPage.tsx` to import `useReducedMotion`, refs/callbacks, and the stage types. Add:

```tsx
const shouldReduceMotion = useReducedMotion() ?? false;
const [phase, setPhase] = useState<AuthPhase>("entering");
const [shouldNavigate, setShouldNavigate] = useState(false);
const timersRef = useRef<Set<number>>(new Set());
const submittedHereRef = useRef(false);
const focusAfterSwitchRef = useRef(false);
const displayNameRef = useRef<HTMLInputElement>(null);
const emailRef = useRef<HTMLInputElement>(null);

const clearTimers = useCallback(() => {
  timersRef.current.forEach((timer) => globalThis.clearTimeout(timer));
  timersRef.current.clear();
}, []);

const schedule = useCallback((callback: () => void, delay: number) => {
  const timer = globalThis.setTimeout(() => {
    timersRef.current.delete(timer);
    callback();
  }, delay);
  timersRef.current.add(timer);
}, []);
```

Use mount/unmount effects to end the entry phase and clean timers. Replace immediate switching with a 330ms midpoint and 700ms completion, using zero delay in reduced-motion mode. When a switch completes, focus `displayNameRef` or `emailRef` from an effect after the new DOM commits.

Update submit behavior exactly as follows:

```tsx
const submit = async (event: FormEvent<HTMLFormElement>) => {
  event.preventDefault();
  clearTimers();
  submittedHereRef.current = true;
  setPhase("submitting");
  try {
    if (mode === "register") {
      await register({ display_name: displayName.trim(), email: email.trim(), password });
    } else {
      await login({ email: email.trim(), password });
    }
    setPhase("success");
    if (shouldReduceMotion) setShouldNavigate(true);
    else schedule(() => setShouldNavigate(true), 680);
  } catch {
    submittedHereRef.current = false;
    setPhase("error");
    schedule(() => setPhase("idle"), shouldReduceMotion ? 0 : 240);
  }
};
```

Navigate immediately for an existing session, but retain the page during a success initiated here:

```tsx
if (shouldNavigate || (user && !submittedHereRef.current)) {
  return <Navigate to={requestedPath || "/"} replace />;
}
```

Wrap the existing controlled form in:

```tsx
<AuthCinematicStage mode={mode} phase={phase} reducedMotion={shouldReduceMotion}>
  {/* existing form header, form fields, error, submit and mode switch */}
</AuthCinematicStage>
```

Disable submit and mode switching only during `loading`, `switching`, `submitting`, or `success`; do not disable fields during the entry animation. Set submit copy to “正在登录…” or “正在创建…” only for `submitting`.

- [ ] **Step 4: Run page tests to verify green state**

Run:

```powershell
npm test -- src/pages/AuthPage.test.tsx
```

Expected: all authentication page tests PASS without timer warnings.

### Task 3: Replace the authentication styling with the cinematic composition

**Files:**
- Modify: `product-frontend/src/styles/global.css:380-625`
- Modify: `product-frontend/src/styles/global.css:1536-1565`
- Modify: `product-frontend/src/styles/global.css:1591-1593`
- Modify: `product-frontend/src/styles/global.css:1654-1661`

- [ ] **Step 1: Add a CSS contract test before changing styles**

Create assertions in `AuthCinematicStage.test.tsx` that require the structural class names:

```tsx
expect(document.querySelectorAll(".zr-auth-curtain")).toHaveLength(2);
expect(document.querySelector(".zr-auth-grain")).toHaveAttribute("aria-hidden", "true");
expect(screen.getByTestId("auth-stage").querySelector(".zr-auth-panel")).toBeInTheDocument();
```

Run the test and expect it to PASS only after Task 1; these assertions protect the selectors that CSS will target.

- [ ] **Step 2: Replace the authentication CSS block**

Implement these fixed rules:

- `.zr-auth-page`: relative isolated two-column grid, `58% 42%`, `min-height: 100svh`, hidden horizontal overflow, story-dark background.
- `.zr-auth-story` and `.zr-auth-panel`: relative z-index above curtains; story uses transparent background and large editorial type; panel uses `#13151a` with a subtle left border.
- `.zr-auth-curtain`: absolute, pointer-events none, top/bottom `-22%`, left `44%`, width `32%`, purple background, transform origin center, cinematic shadow.
- `.zr-auth-curtain--back`: lower z-index, lower opacity, lighter purple, left `37%`, width `24%`.
- `.zr-auth-grain`: one fixed inset layer with low-opacity inline SVG noise and pointer-events none.
- `.zr-auth-success`: full-screen fixed overlay above the form, centered status copy, brand-purple background.
- `.zr-auth-submit`: relative overflow hidden; `[data-phase="submitting"]` adds a one-way pseudo-element shine.
- `.zr-auth-field input:focus-visible`: brand underline and existing global focus ring compatibility.
- `[data-phase="switching"]` and `[data-phase="success"]`: prevent duplicate clicks through disabled controls, while curtain layers remain non-interactive.

Do not add continuous idle animation or global pointer listeners.

- [ ] **Step 3: Implement responsive and reduced-motion CSS**

At `max-width: 760px`, change the auth page to one column, set story to a compact minimum height, remove the panel left border, keep vertical scrolling, reduce headline size, and adjust curtain position/width. At `max-width: 560px`, tighten form spacing without reducing touch targets below 44px.

Extend the existing reduced-motion media query with:

```css
  .zr-auth-grain {
    display: none;
  }

  .zr-auth-curtain,
  .zr-auth-success,
  .zr-auth-story__copy,
  .zr-auth-form-wrap {
    animation: none !important;
    filter: none !important;
    transform: none !important;
  }
```

- [ ] **Step 4: Run focused tests and production build**

Run:

```powershell
npm test -- src/components/AuthCinematicStage.test.tsx src/pages/AuthPage.test.tsx
npm run build
```

Expected: focused tests PASS and TypeScript/Vite build exits 0.

### Task 4: Regression and browser verification

**Files:**
- Verify only; do not modify unrelated files.

- [ ] **Step 1: Run the full frontend suite**

Run:

```powershell
npm test
```

Expected: all Vitest suites PASS.

- [ ] **Step 2: Inspect the final diff**

Run from the repository root:

```powershell
git diff --check
git diff -- product-frontend/package.json product-frontend/package-lock.json product-frontend/src/components/AuthCinematicStage.tsx product-frontend/src/components/AuthCinematicStage.test.tsx product-frontend/src/pages/AuthPage.tsx product-frontend/src/pages/AuthPage.test.tsx product-frontend/src/styles/global.css
```

Expected: no whitespace errors; diff contains only the approved auth motion work plus pre-existing user changes already present in overlapping files.

- [ ] **Step 3: Verify in a real browser**

Start Vite and verify:

1. Desktop at 1440×900: entry finishes within 700ms and form is usable during entry.
2. Toggle login/register repeatedly: one curtain transition runs at a time and focus moves to the first field.
3. Submit invalid credentials: 4px form feedback and accessible error, no full-screen flash.
4. Submit valid credentials: success curtain appears, then returns to the requested route.
5. Mobile at 390×844: no horizontal overflow and the form remains usable when the virtual keyboard reduces viewport height.
6. Emulate `prefers-reduced-motion: reduce`: no sweep or blur and success navigation is immediate.

- [ ] **Step 4: Leave overlapping dirty files unstaged**

Because `AuthPage.tsx` and `global.css` were already modified before this task, do not auto-commit the implementation. Report the exact modified files and verification results to the user so they can decide how to group the existing work.
