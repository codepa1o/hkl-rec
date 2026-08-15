import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ComponentProps } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
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

vi.mock("../context/AuthContext", () => ({ useAuth: () => authState }));

function renderPage(
  initialEntries: ComponentProps<typeof MemoryRouter>["initialEntries"] = ["/auth"],
) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <Routes>
        <Route path="/auth" element={<AuthPage />} />
        <Route path="*" element={<span>目标页面</span>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("AuthPage", () => {
  beforeEach(() => {
    authState.user = null;
    authState.error = null;
    authState.login.mockReset();
    authState.register.mockReset();
    authState.clearError.mockReset();
  });

  it("默认展示清晰可访问的中文登录表单", () => {
    renderPage();

    expect(screen.getByRole("heading", { name: "继续你的阅读脉络" })).toBeInTheDocument();
    expect(screen.getByLabelText("邮箱")).toBeInTheDocument();
    expect(screen.getByLabelText("密码")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "登录" })).toBeInTheDocument();
  });

  it("可切换注册并提交显示名称、邮箱和密码", async () => {
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
