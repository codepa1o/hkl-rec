import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ReadingProvider } from "./ReadingContext";
import ReadingActions from "./ReadingActions";
import PreferenceRules from "./PreferenceRules";
import SavedSearchButton from "./SavedSearchButton";
import ReadingLibrary from "./ReadingLibrary";

const account = { user_id: 42, display_name: "我的账号" };
vi.mock("../context/AuthContext", () => ({ useAuth: () => ({ user: account }) }));
vi.mock("../context/SourceSpaceContext", () => ({ useSourceSpace: () => ({ sourceSpace: "mind" }) }));
vi.mock("../context/PersonaContext", () => ({ usePersona: () => ({ selectedPersona: account }) }));

function wrap(children: React.ReactNode) {
  return render(<MemoryRouter><ReadingProvider>{children}</ReadingProvider></MemoryRouter>);
}

describe("中文阅读工具", () => {
  beforeEach(() => { vi.restoreAllMocks(); sessionStorage.clear(); });

  it("收藏和已读独立更新，失败不展示成功状态", async () => {
    const writes: unknown[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
      if (url.includes("/reading/states")) return new Response(JSON.stringify({ items: [{ source_space: "mind", article_id: "N1", saved: false, read: false }] }));
      const body = JSON.parse(String(init?.body)); writes.push(body);
      if (body.read) return new Response(JSON.stringify({ detail: "保存失败，请重试" }), { status: 503 });
      return new Response(JSON.stringify({ source_space: "mind", article_id: "N1", saved: body.saved, read: false }));
    }));
    wrap(<ReadingActions sourceSpace="mind" articleId="N1" />);
    const save = await screen.findByRole("button", { name: "收藏文章" });
    await waitFor(() => expect(save).toBeEnabled());
    fireEvent.click(save);
    expect(await screen.findByRole("button", { name: "取消收藏" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "标为已读" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("保存失败");
    expect(screen.getByRole("button", { name: "标为已读" })).toHaveAttribute("aria-pressed", "false");
    expect(writes).toEqual([{ source_space: "mind", article_id: "N1", saved: true }, { source_space: "mind", article_id: "N1", read: true }]);
  });

  it("偏好表单支持中文短语、强制屏蔽和暂停", async () => {
    let rules: unknown[] = [];
    const writes: Record<string, unknown>[] = [];
    vi.stubGlobal("fetch", vi.fn(async (_url: string, init?: RequestInit) => {
      if (init?.method === "POST") {
        const body = JSON.parse(String(init.body)); writes.push(body);
        rules = [{ ...body, id: 1 }];
        return new Response(JSON.stringify(rules[0]));
      }
      return new Response(JSON.stringify({ items: rules }));
    }));
    wrap(<PreferenceRules />);
    fireEvent.change(screen.getByLabelText("规则类型"), { target: { value: "keyword" } });
    fireEvent.change(screen.getByLabelText("匹配内容"), { target: { value: "人工智能" } });
    fireEvent.change(screen.getByLabelText("处理方式"), { target: { value: "block" } });
    fireEvent.click(screen.getByRole("button", { name: "添加规则" }));
    expect(await screen.findByText("人工智能")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "暂停规则" }));
    await waitFor(() => expect(writes.at(-1)?.enabled).toBe(false));
    expect(writes[0]).toMatchObject({ value: "人工智能", effect: "block", source_space: "mind" });
  });

  it("保存搜索保留查询条件，不提交用户编号", async () => {
    const writes: unknown[] = [];
    vi.stubGlobal("fetch", vi.fn(async (_url: string, init?: RequestInit) => {
      const body = JSON.parse(String(init?.body)); writes.push(body);
      return new Response(JSON.stringify({ ...body, id: 3 }));
    }));
    wrap(<SavedSearchButton query="人工智能" language="all" category={null} />);
    fireEvent.click(screen.getByRole("button", { name: "保存此搜索" }));
    expect(await screen.findByText("搜索已保存")).toBeInTheDocument();
    expect(writes).toEqual([{ source_space: "mind", query: "人工智能", language: "all", category: null }]);
  });

  it("收藏列表保留失效文章，保存搜索恢复正确的空间和筛选", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url.includes("/reading/searches")) return new Response(JSON.stringify({ items: [{ id: 7, source_space: "mind", query: "climate", language: "all", category: "news" }] }));
      if (url.includes("/reading/states")) return new Response(JSON.stringify({ items: [{ source_space: "mind", article_id: "N1", saved: true, read: false }] }));
      return new Response(JSON.stringify({ items: [{ source_space: "mind", article_id: "N1", saved: true, read: false, title: "已失效报道", source_domain: "example.com", url: "https://example.com/1", available: false }], has_more: false }));
    }));
    wrap(<ReadingLibrary />);
    expect(await screen.findByText("已失效报道")).toBeInTheDocument();
    expect(screen.getByText("文章已不可用，收藏记录仍保留")).toBeInTheDocument();
    const savedQuery = await screen.findByRole("link", { name: "climate" });
    expect(savedQuery).toHaveAttribute("href", "/search?q=climate&space=mind&category=news");
  });
});
