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

vi.mock("../api/client", () => ({
  listSearchSuggestions: vi.fn().mockResolvedValue({ items: [] }),
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
    expect(screen.getByText("搜索")).toBeInTheDocument();
    expect(screen.getByText("兴趣画像")).toBeInTheDocument();
    expect(screen.getByText("新闻分类")).toBeInTheDocument();
    expect(screen.getAllByPlaceholderText("搜索新闻")).toHaveLength(2);
    expect(screen.getByLabelText("切换为深色主题")).toBeInTheDocument();
    expect(screen.getByText("加载中…")).toBeInTheDocument();
    expect(screen.queryByText("热门")).not.toBeInTheDocument();
    expect(screen.queryByText("探索")).not.toBeInTheDocument();
  });
});
