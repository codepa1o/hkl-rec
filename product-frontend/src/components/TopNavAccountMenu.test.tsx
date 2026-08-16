import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ThemeProvider } from "../context/ThemeContext";
import TopNav from "./TopNav";

const mocks = vi.hoisted(() => ({
  logout: vi.fn().mockResolvedValue(undefined),
  selectPersona: vi.fn(),
}));

vi.mock("../context/AuthContext", () => ({
  useAuth: () => ({
    user: {
      user_id: 7004,
      email: "hukelang@example.com",
      display_name: "胡科浪",
    },
    logout: mocks.logout,
  }),
}));

vi.mock("../context/PersonaContext", () => ({
  usePersona: () => ({
    personas: [
      { user_id: 7004, display_name: "胡科浪", behavior_score: 0, top_topics: [] },
      { user_id: 7001, display_name: "Sports Reader", behavior_score: 1, top_topics: [] },
    ],
    selectedPersona: {
      user_id: 7004,
      display_name: "胡科浪",
      behavior_score: 0,
      top_topics: [],
    },
    selectPersona: mocks.selectPersona,
    loading: false,
    error: null,
  }),
}));

vi.mock("../api/client", () => ({
  listSearchSuggestions: vi.fn().mockResolvedValue({ items: [] }),
}));

function renderTopNav() {
  return render(
    <MemoryRouter>
      <ThemeProvider>
        <TopNav />
      </ThemeProvider>
    </MemoryRouter>,
  );
}

describe("顶部账号菜单", () => {
  beforeEach(() => {
    mocks.logout.mockClear();
    mocks.selectPersona.mockClear();
  });

  it("默认只显示一次登录姓名，并提供统一账号入口", () => {
    renderTopNav();

    expect(screen.getAllByText("胡科浪")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "打开账号菜单" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
    expect(screen.queryByRole("button", { name: "退出登录" })).not.toBeInTheDocument();
  });

  it("展开后显示邮箱、画像列表和当前状态", () => {
    renderTopNav();

    fireEvent.click(screen.getByRole("button", { name: "打开账号菜单" }));

    expect(screen.getByText("hukelang@example.com")).toBeInTheDocument();
    expect(screen.getByText("推荐画像")).toBeInTheDocument();
    expect(screen.getByText("我的画像")).toBeInTheDocument();
    expect(screen.getByText("体育读者")).toBeInTheDocument();
    expect(screen.getByText("当前")).toBeInTheDocument();
    expect(screen.getByTestId("account-persona-indicator").style.getPropertyValue(
      "--zr-selection-index",
    )).toBe("0");
    expect(screen.getByRole("button", { name: "退出登录" })).toBeInTheDocument();
  });

  it("选择画像后切换并关闭菜单", () => {
    renderTopNav();

    fireEvent.click(screen.getByRole("button", { name: "打开账号菜单" }));
    fireEvent.click(screen.getByRole("menuitemradio", { name: "体育读者" }));

    expect(mocks.selectPersona).toHaveBeenCalledWith(7001);
    expect(screen.queryByText("hukelang@example.com")).not.toBeInTheDocument();
  });

  it("按 Escape 关闭菜单", () => {
    renderTopNav();

    fireEvent.click(screen.getByRole("button", { name: "打开账号菜单" }));
    fireEvent.keyDown(document, { key: "Escape" });

    expect(screen.queryByText("hukelang@example.com")).not.toBeInTheDocument();
  });

  it("点击菜单外部后关闭菜单", () => {
    renderTopNav();

    fireEvent.click(screen.getByRole("button", { name: "打开账号菜单" }));
    fireEvent.mouseDown(document.body);

    expect(screen.queryByText("hukelang@example.com")).not.toBeInTheDocument();
  });

  it("从菜单执行退出登录", async () => {
    renderTopNav();

    fireEvent.click(screen.getByRole("button", { name: "打开账号菜单" }));
    fireEvent.click(screen.getByRole("button", { name: "退出登录" }));

    await waitFor(() => expect(mocks.logout).toHaveBeenCalledTimes(1));
  });

  it("退出失败时显示中文提示", async () => {
    mocks.logout.mockRejectedValueOnce(new Error("network error"));
    renderTopNav();

    fireEvent.click(screen.getByRole("button", { name: "打开账号菜单" }));
    fireEvent.click(screen.getByRole("button", { name: "退出登录" }));

    expect(await screen.findByText("退出失败，请稍后重试")).toBeInTheDocument();
  });
});
