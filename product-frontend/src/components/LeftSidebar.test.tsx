import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { listCategories } from "../api/client";
import LeftSidebar from "./LeftSidebar";

const sourceState = { sourceSpace: "mind" as "mind" | "live" };

vi.mock("../context/SourceSpaceContext", () => ({
  useSourceSpace: () => sourceState,
}));

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
    sourceState.sourceSpace = "mind";
    vi.clearAllMocks();
    vi.mocked(listCategories).mockResolvedValue({
      source_space: "mind",
      items: categoryKeys.map((key, index) => ({
        key,
        news_count: 20_000 - index,
      })),
    });
  });

  it("实时空间展示自己的分类且分类链接保留语言", async () => {
    sourceState.sourceSpace = "live";
    vi.mocked(listCategories).mockResolvedValue({source_space: "live", items: [{key: "live-technology", news_count: 10}]});
    render(
      <MemoryRouter initialEntries={["/?category=live-technology&language=zh"]}>
        <LeftSidebar />
      </MemoryRouter>,
    );

    expect(await screen.findByRole("link", {name: "科技"})).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", {name: "科技"})).toHaveAttribute("href", "/?language=zh&category=live-technology");
    expect(screen.getByRole("link", {name: "全部新闻"})).toHaveAttribute("href", "/?language=zh");
    expect(listCategories).toHaveBeenCalledWith("live");
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

  it("兴趣画像入口导航到独立页面并显示激活态", async () => {
    render(
      <MemoryRouter initialEntries={["/profile"]}>
        <LeftSidebar />
      </MemoryRouter>,
    );

    const profileLink = screen.getByRole("link", { name: "兴趣画像" });
    expect(profileLink).toHaveAttribute("href", "/profile");
    expect(profileLink).toHaveAttribute("aria-current", "page");
    expect(
      screen
        .getByTestId("primary-navigation-indicator")
        .style.getPropertyValue("--zr-selection-index"),
    ).toBe("2");
    expect(await screen.findByRole("link", { name: "全部新闻" })).not.toHaveAttribute(
      "aria-current",
    );
  });

  it("使用共享选中框平滑更新主导航和新闻分类的位置", async () => {
    render(
      <MemoryRouter>
        <LeftSidebar />
      </MemoryRouter>,
    );

    const categoryIndicator = await screen.findByTestId("news-category-indicator");
    const primaryIndicator = screen.getByTestId("primary-navigation-indicator");
    expect(categoryIndicator.style.getPropertyValue("--zr-selection-index")).toBe("0");
    expect(categoryIndicator.style.getPropertyValue("--zr-selection-offset")).toBe("0px");
    expect(primaryIndicator.style.getPropertyValue("--zr-selection-index")).toBe("0");

    fireEvent.click(screen.getByRole("link", { name: "体育" }));
    await waitFor(() =>
      expect(categoryIndicator.style.getPropertyValue("--zr-selection-index")).toBe("14"),
    );
    expect(categoryIndicator.style.getPropertyValue("--zr-selection-offset")).toBe("616px");

    fireEvent.click(screen.getByRole("link", { name: "搜索" }));
    await waitFor(() =>
      expect(primaryIndicator.style.getPropertyValue("--zr-selection-index")).toBe("1"),
    );
    expect(primaryIndicator.style.getPropertyValue("--zr-selection-offset")).toBe("49px");
  });
});
