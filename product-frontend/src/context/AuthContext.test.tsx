import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { getCurrentUser, login, logout, UNAUTHORIZED_EVENT } from "../api/client";
import { AuthProvider, useAuth } from "./AuthContext";

vi.mock("../api/client", () => ({
  UNAUTHORIZED_EVENT: "newsrec:unauthorized",
  getCurrentUser: vi.fn(),
  login: vi.fn(),
  logout: vi.fn(),
  register: vi.fn(),
}));

function Probe() {
  const auth = useAuth();
  if (auth.loading) return <span>恢复中</span>;
  return (
    <div>
      <span>{auth.user?.display_name ?? "未登录"}</span>
      <button onClick={() => void auth.login({ email: "reader@example.com", password: "news-password" })}>
        登录
      </button>
      <button onClick={() => void auth.logout()}>退出</button>
    </div>
  );
}

function renderAuth(children: ReactNode = <Probe />) {
  return render(<AuthProvider>{children}</AuthProvider>);
}

describe("AuthProvider", () => {
  beforeEach(() => {
    vi.mocked(getCurrentUser).mockReset();
    vi.mocked(login).mockReset();
    vi.mocked(logout).mockReset();
  });

  it("启动时恢复已有 HttpOnly Cookie 会话", async () => {
    vi.mocked(getCurrentUser).mockResolvedValue({
      user_id: 7004,
      email: "reader@example.com",
      display_name: "新闻读者",
    });

    renderAuth();

    expect(screen.getByText("恢复中")).toBeInTheDocument();
    expect(await screen.findByText("新闻读者")).toBeInTheDocument();
  });

  it("无会话时进入未登录状态，成功登录后更新用户", async () => {
    vi.mocked(getCurrentUser).mockRejectedValue(new Error("请先登录"));
    vi.mocked(login).mockResolvedValue({
      user_id: 7004,
      email: "reader@example.com",
      display_name: "新闻读者",
    });
    renderAuth();
    await screen.findByText("未登录");

    fireEvent.click(screen.getByRole("button", { name: "登录" }));

    expect(await screen.findByText("新闻读者")).toBeInTheDocument();
  });

  it("退出后清空当前用户", async () => {
    vi.mocked(getCurrentUser).mockResolvedValue({
      user_id: 7004,
      email: "reader@example.com",
      display_name: "新闻读者",
    });
    vi.mocked(logout).mockResolvedValue(undefined);
    renderAuth();
    await screen.findByText("新闻读者");

    fireEvent.click(screen.getByRole("button", { name: "退出" }));

    await waitFor(() => expect(screen.getByText("未登录")).toBeInTheDocument());
  });

  it("业务请求收到 401 后立即清空过期会话", async () => {
    vi.mocked(getCurrentUser).mockResolvedValue({
      user_id: 7004,
      email: "reader@example.com",
      display_name: "新闻读者",
    });
    renderAuth();
    await screen.findByText("新闻读者");

    globalThis.dispatchEvent(new Event(UNAUTHORIZED_EVENT));

    await waitFor(() => expect(screen.getByText("未登录")).toBeInTheDocument());
  });
});
