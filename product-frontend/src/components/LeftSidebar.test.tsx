import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { listCategories } from "../api/client";
import LeftSidebar from "./LeftSidebar";

vi.mock("../api/client", () => ({
  listCategories: vi.fn(),
}));

const categoryKeys = [
  "autos",
  "entertainment",
  "finance",
  "foodanddrink",
  "games",
  "health",
  "kids",
  "lifestyle",
  "middleeast",
  "movies",
  "music",
  "news",
  "northamerica",
  "sports",
  "travel",
  "tv",
  "video",
  "weather",
];

describe("LeftSidebar 新闻分类", () => {
  beforeEach(() => {
    vi.mocked(listCategories).mockResolvedValue({
      items: categoryKeys.map((key, index) => ({
        key,
        news_count: 20_000 - index,
      })),
    });
  });

  it("展示全部一级分类并高亮当前分类", async () => {
    render(
      <MemoryRouter initialEntries={["/?category=sports"]}>
        <LeftSidebar />
      </MemoryRouter>,
    );

    expect(screen.getByRole("link", { name: "全部新闻" })).toHaveAttribute("href", "/");
    expect(await screen.findByRole("link", { name: "体育" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    await waitFor(() =>
      expect(screen.getAllByTestId("news-category-link")).toHaveLength(18),
    );
    expect(screen.getByRole("link", { name: "游戏" })).toBeInTheDocument();
  });

  it("分类接口失败时保留全部新闻入口和中文重试按钮", async () => {
    vi.mocked(listCategories).mockRejectedValueOnce(new Error("network"));
    render(
      <MemoryRouter>
        <LeftSidebar />
      </MemoryRouter>,
    );

    expect(screen.getByRole("link", { name: "全部新闻" })).toBeInTheDocument();
    expect(await screen.findByText("分类加载失败")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重新加载" })).toBeInTheDocument();
  });
});
