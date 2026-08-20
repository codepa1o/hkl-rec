import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { MemoryRouter, useLocation } from "react-router-dom";
import SearchBox from "./SearchBox";
import { listSearchSuggestions } from "../api/client";

const sourceState = { sourceSpace: "mind" as "mind" | "live" };

vi.mock("../context/SourceSpaceContext", () => ({
  useSourceSpace: () => sourceState,
}));

vi.mock("../api/client", () => ({
  listSearchSuggestions: vi.fn(),
}));

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{`${location.pathname}${location.search}`}</output>;
}

function renderSearchBox(initialEntry = "/", initialQuery = "") {
  render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <SearchBox initialQuery={initialQuery} />
      <LocationProbe />
    </MemoryRouter>,
  );
}

describe("搜索框操作区", () => {
  beforeEach(() => {
    sourceState.sourceSpace = "mind";
    vi.mocked(listSearchSuggestions).mockResolvedValue({
      source_space: "mind",
      items: [],
    });
  });

  it("按当前新闻空间请求搜索建议", async () => {
    sourceState.sourceSpace = "live";
    renderSearchBox();
    fireEvent.change(screen.getByPlaceholderText("搜索新闻"), {
      target: { value: "climate" },
    });

    await new Promise((resolve) => window.setTimeout(resolve, 250));
    expect(listSearchSuggestions).toHaveBeenCalledWith(8, "live");
  });

  it("空内容时隐藏清空按钮并禁用搜索按钮", () => {
    renderSearchBox();

    expect(screen.queryByRole("button", { name: "清空搜索内容" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "搜索" })).toBeDisabled();
  });

  it("点击搜索按钮时去除首尾空格并进入搜索结果页", () => {
    renderSearchBox();
    const input = screen.getByPlaceholderText("搜索新闻");

    fireEvent.change(input, { target: { value: "  climate change  " } });
    fireEvent.click(screen.getByRole("button", { name: "搜索" }));

    expect(screen.getByTestId("location")).toHaveTextContent("/search?q=climate%20change");
  });

  it("按 Enter 时执行与搜索按钮相同的搜索", () => {
    renderSearchBox();
    const input = screen.getByPlaceholderText("搜索新闻");

    fireEvent.change(input, { target: { value: "sports" } });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(screen.getByTestId("location")).toHaveTextContent("/search?q=sports");
  });

  it("在搜索结果页清空内容并重置结果，同时保持输入焦点", () => {
    renderSearchBox("/search?q=climate", "climate");
    const input = screen.getByPlaceholderText("搜索新闻");

    fireEvent.click(screen.getByRole("button", { name: "清空搜索内容" }));

    expect(input).toHaveValue("");
    expect(input).toHaveFocus();
    expect(screen.getByTestId("location")).toHaveTextContent("/search");
    expect(screen.queryByRole("button", { name: "清空搜索内容" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "搜索" })).toBeDisabled();
  });

  it("在非搜索页面清空内容时保留当前页面", () => {
    renderSearchBox("/", "climate");

    fireEvent.click(screen.getByRole("button", { name: "清空搜索内容" }));

    expect(screen.getByTestId("location")).toHaveTextContent("/");
  });
});
