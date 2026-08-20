import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import LeftSidebar from "./LeftSidebar";
import SearchBox from "./SearchBox";
import TopNav from "./TopNav";
import { ThemeProvider } from "../context/ThemeContext";

vi.mock("../context/PersonaContext", () => ({
  usePersona: () => ({ personas: [], selectedPersona: null, loading: true }),
}));

vi.mock("../context/AuthContext", () => ({
  useAuth: () => ({
    user: { user_id: 7004, email: "reader@example.com", display_name: "新闻读者" },
    logout: vi.fn(),
  }),
}));

vi.mock("../context/SourceSpaceContext", () => ({
  useSourceSpace: () => ({
    sourceSpace: "mind",
    liveEnabled: true,
    loading: false,
    selectSourceSpace: vi.fn(),
  }),
}));

vi.mock("../api/client", () => ({
  listCategories: vi.fn().mockResolvedValue({ source_space: "mind", items: [] }),
  listSearchSuggestions: vi.fn().mockResolvedValue({ source_space: "mind", items: [] }),
}));

describe("中文界面", () => {
  it("导航和搜索控件使用中文", () => {
    render(
      <MemoryRouter>
        <ThemeProvider>
          <TopNav />
        </ThemeProvider>
        <LeftSidebar />
        <SearchBox />
      </MemoryRouter>,
    );

    expect(screen.getByText("首页")).toBeInTheDocument();
    expect(screen.getByText("新闻意图推荐")).toBeInTheDocument();
    const searchButtons = screen.getAllByRole("button", { name: "搜索" });
    expect(searchButtons).toHaveLength(2);
    searchButtons.forEach((button) => expect(button).toBeDisabled());
    expect(screen.getByText("兴趣画像")).toBeInTheDocument();
    expect(screen.getByText("新闻分类")).toBeInTheDocument();
    expect(screen.getAllByPlaceholderText("搜索新闻")).toHaveLength(2);
    expect(screen.getByLabelText("切换为深色主题")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "打开账号菜单" })).toBeInTheDocument();
    expect(screen.getByText("新闻读者")).toBeInTheDocument();
    expect(screen.queryByText("热门")).not.toBeInTheDocument();
    expect(screen.queryByText("探索")).not.toBeInTheDocument();
  });
});
