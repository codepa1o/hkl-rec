import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ComponentProps } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AuthUser } from "../api/types";
import AuthPage from "./AuthPage";

const authState = {
  user: null as AuthUser | null,
  loading: false,
  error: null as string | null,
  login: vi.fn(),
  register: vi.fn(),
  logout: vi.fn(),
  clearError: vi.fn(),
};

const motionPreference = vi.hoisted(() => ({ value: false }));

vi.mock("../context/AuthContext", () => ({ useAuth: () => authState }));
vi.mock("motion/react", async (importOriginal) => {
  const actual = await importOriginal<typeof import("motion/react")>();
  return { ...actual, useReducedMotion: () => motionPreference.value };
});

function authPageTree(
  initialEntries: ComponentProps<typeof MemoryRouter>["initialEntries"] = ["/auth"],
) {
  return (
    <MemoryRouter initialEntries={initialEntries}>
      <Routes>
        <Route path="/auth" element={<AuthPage />} />
        <Route path="*" element={<span>目标页面</span>} />
      </Routes>
    </MemoryRouter>
  );
}

function renderPage(
  initialEntries: ComponentProps<typeof MemoryRouter>["initialEntries"] = ["/auth"],
) {
  return render(authPageTree(initialEntries));
}

describe("AuthPage", () => {
  beforeEach(() => {
    authState.user = null;
    authState.loading = false;
    authState.error = null;
    authState.login.mockReset();
    authState.register.mockReset();
    authState.clearError.mockReset();
    motionPreference.value = false;
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("默认展示清晰可访问的中文登录表单", () => {
    renderPage();

    expect(screen.getByRole("heading", { name: "继续你的阅读脉络" })).toBeInTheDocument();
    expect(screen.getByLabelText("邮箱")).toBeInTheDocument();
    expect(screen.getByLabelText("密码")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "登录" })).toBeInTheDocument();
  });

  it("可切换注册并提交显示名称、邮箱和密码", async () => {
    motionPreference.value = true;
    authState.register.mockResolvedValue(undefined);
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "创建账号" }));

    fireEvent.change(screen.getByLabelText("显示名称"), { target: { value: "新闻读者" } });
    fireEvent.change(screen.getByLabelText("邮箱"), { target: { value: "reader@example.com" } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "news-password" } });
    fireEvent.submit(screen.getByRole("button", { name: "完成注册" }).closest("form")!);

    await waitFor(() =>
      expect(authState.register).toHaveBeenCalledWith({
        display_name: "新闻读者",
        email: "reader@example.com",
        password: "news-password",
      }),
    );
  });

  it("以电影式转场切换注册模式并将焦点交给第一个字段", async () => {
    vi.useFakeTimers();
    renderPage();

    fireEvent.click(screen.getByRole("button", { name: "创建账号" }));
    expect(screen.getByTestId("auth-stage")).toHaveAttribute("data-phase", "switching");

    await act(async () => {
      vi.advanceTimersByTime(700);
    });

    expect(screen.getByRole("heading", { name: "建立你的阅读坐标" })).toBeInTheDocument();
    expect(screen.getByLabelText("显示名称")).toHaveFocus();
    expect(screen.getByTestId("auth-stage")).toHaveAttribute("data-phase", "idle");
  });

  it("提交成功后等待收幕完成再回到受保护路由", async () => {
    vi.useFakeTimers();
    authState.login.mockImplementation(async () => {
      authState.user = {
        user_id: 7004,
        email: "reader@example.com",
        display_name: "新闻读者",
      };
    });
    renderPage([{ pathname: "/auth", state: { from: { pathname: "/search" } } }]);

    fireEvent.change(screen.getByLabelText("邮箱"), { target: { value: "reader@example.com" } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "news-password" } });
    await act(async () => {
      fireEvent.submit(screen.getByRole("button", { name: "登录" }).closest("form")!);
      await Promise.resolve();
    });

    expect(screen.getByRole("status")).toHaveTextContent("阅读世界正在展开");
    expect(screen.queryByText("目标页面")).not.toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(679);
    });
    expect(screen.queryByText("目标页面")).not.toBeInTheDocument();

    await act(async () => {
      vi.advanceTimersByTime(1);
    });
    expect(screen.getByText("目标页面")).toBeInTheDocument();
  });

  it("减少动效模式下提交成功后立即导航", async () => {
    motionPreference.value = true;
    authState.login.mockImplementation(async () => {
      authState.user = {
        user_id: 7004,
        email: "reader@example.com",
        display_name: "新闻读者",
      };
    });
    renderPage([{ pathname: "/auth", state: { from: { pathname: "/search" } } }]);

    fireEvent.change(screen.getByLabelText("邮箱"), { target: { value: "reader@example.com" } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "news-password" } });
    await act(async () => {
      fireEvent.submit(screen.getByRole("button", { name: "登录" }).closest("form")!);
      await Promise.resolve();
    });

    expect(screen.getByText("目标页面")).toBeInTheDocument();
  });

  it("提交等待期间开启减少动效后成功立即导航", async () => {
    vi.useFakeTimers();
    let resolveLogin!: () => void;
    authState.login.mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          resolveLogin = () => {
            authState.user = {
              user_id: 7004,
              email: "reader@example.com",
              display_name: "新闻读者",
            };
            resolve();
          };
        }),
    );
    const entries = [{ pathname: "/auth", state: { from: { pathname: "/search" } } }];
    const view = renderPage(entries);

    fireEvent.change(screen.getByLabelText("邮箱"), { target: { value: "reader@example.com" } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "news-password" } });
    fireEvent.submit(screen.getByRole("button", { name: "登录" }).closest("form")!);
    expect(screen.getByTestId("auth-stage")).toHaveAttribute("data-phase", "submitting");

    motionPreference.value = true;
    view.rerender(authPageTree(entries));
    await act(async () => {
      resolveLogin();
      await Promise.resolve();
    });

    expect(screen.getByText("目标页面")).toBeInTheDocument();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("成功收幕期间开启减少动效会立即完成导航", async () => {
    vi.useFakeTimers();
    authState.login.mockImplementation(async () => {
      authState.user = {
        user_id: 7004,
        email: "reader@example.com",
        display_name: "新闻读者",
      };
    });
    const entries = [{ pathname: "/auth", state: { from: { pathname: "/search" } } }];
    const view = renderPage(entries);

    fireEvent.change(screen.getByLabelText("邮箱"), { target: { value: "reader@example.com" } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "news-password" } });
    await act(async () => {
      fireEvent.submit(screen.getByRole("button", { name: "登录" }).closest("form")!);
      await Promise.resolve();
    });
    expect(screen.getByRole("status")).toHaveTextContent("阅读世界正在展开");

    motionPreference.value = true;
    view.rerender(authPageTree(entries));

    expect(screen.getByText("目标页面")).toBeInTheDocument();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("请求尚未完成时卸载不会遗留状态更新或导航计时器", async () => {
    vi.useFakeTimers();
    let resolveLogin!: () => void;
    authState.login.mockImplementation(
      () =>
        new Promise<void>((resolve) => {
          resolveLogin = resolve;
        }),
    );
    const view = renderPage();

    fireEvent.change(screen.getByLabelText("邮箱"), { target: { value: "reader@example.com" } });
    fireEvent.change(screen.getByLabelText("密码"), { target: { value: "news-password" } });
    fireEvent.submit(screen.getByRole("button", { name: "登录" }).closest("form")!);
    view.unmount();

    await act(async () => {
      resolveLogin();
      await Promise.resolve();
    });

    expect(vi.getTimerCount()).toBe(0);
  });

  it("显示后端返回的统一错误", () => {
    authState.error = "邮箱或密码错误";
    renderPage();

    expect(screen.getByRole("alert")).toHaveTextContent("邮箱或密码错误");
  });

  it("进入页面时清理上一次请求留下的错误", () => {
    renderPage();

    expect(authState.clearError).toHaveBeenCalledTimes(1);
  });

  it("登录成功后回到受保护路由原位置", async () => {
    authState.user = {
      user_id: 7004,
      email: "reader@example.com",
      display_name: "新闻读者",
    };
    renderPage([{ pathname: "/auth", state: { from: { pathname: "/search" } } }]);

    expect(await screen.findByText("目标页面")).toBeInTheDocument();
  });
});
