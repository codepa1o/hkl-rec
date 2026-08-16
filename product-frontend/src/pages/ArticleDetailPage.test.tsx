import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  getArticleCard,
  newClientId,
  sendTrackedEventKeepalive,
  trackEvent,
} from "../api/client";
import ArticleDetailPage from "./ArticleDetailPage";

const bumpProfile = vi.fn();

vi.mock("../context/PersonaContext", () => ({
  usePersona: () => ({
    selectedPersona: {
      user_id: 7004,
      display_name: "Reader",
      behavior_score: 0,
      top_topics: [],
    },
    bumpProfile,
  }),
}));

vi.mock("../api/client", () => ({
  getArticleCard: vi.fn(),
  newClientId: vi.fn(),
  sendTrackedEventKeepalive: vi.fn(),
  trackEvent: vi.fn(),
}));

const article = {
  news_id: "N301",
  title: "A detailed article",
  abstract: "Article abstract",
  url: "https://example.com/N301",
  source_domain: "example.com",
  category: "news",
  subcategory: "world",
  categories: [{ topic_id: 1, display_name: "News" }],
  title_entities: [
    {
      label: "Ada Lovelace",
      entity_type: "person",
      type_code: "P",
      wikidata_id: "Q7259",
      confidence: 1,
      surface_forms: ["Ada"],
    },
    {
      label: "OpenAI",
      entity_type: "organization",
      type_code: "O",
      wikidata_id: "Q24283660",
      confidence: 0.91,
      surface_forms: ["OpenAI"],
    },
  ],
  abstract_entities: [
    {
      label: "Ada Lovelace",
      entity_type: "person",
      type_code: "P",
      wikidata_id: "Q7259",
      confidence: 0.8,
      surface_forms: ["Lovelace"],
    },
    {
      label: "London",
      entity_type: "location",
      type_code: "G",
      wikidata_id: "Q84",
      confidence: 0.95,
      surface_forms: ["London"],
    },
  ],
};

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/articles/N301"]}>
      <Routes>
        <Route path="/articles/:newsId" element={<ArticleDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ArticleDetailPage entities", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(newClientId).mockReturnValue("route-load-1");
    vi.mocked(getArticleCard).mockResolvedValue(article as never);
    vi.mocked(trackEvent).mockResolvedValue({
      ok: true,
      event_type: "detail_view",
      profile_updated: false,
      behavior_score: null,
    });
  });

  it("只在详情页按人物、机构和地点分组展示实体，并按 Wikidata ID 去重", async () => {
    renderPage();

    expect(await screen.findByRole("heading", { name: "相关实体" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "人物" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "机构" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "地点" })).toBeInTheDocument();
    expect(screen.getAllByText("Ada Lovelace")).toHaveLength(1);
    expect(screen.getByText("OpenAI")).toBeInTheDocument();
    expect(screen.getByText("London")).toBeInTheDocument();
  });

  it("没有实体时不渲染相关实体区域", async () => {
    vi.mocked(getArticleCard).mockResolvedValue({
      ...article,
      title_entities: [],
      abstract_entities: [],
    } as never);
    renderPage();

    expect(await screen.findByText("A detailed article")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "相关实体" })).not.toBeInTheDocument();
  });
});

describe("ArticleDetailPage visible dwell", () => {
  let now = 0;

  beforeEach(() => {
    vi.clearAllMocks();
    now = 0;
    vi.spyOn(performance, "now").mockImplementation(() => now);
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "visible",
    });
    vi.mocked(newClientId).mockReturnValue("route-load-1");
    vi.mocked(getArticleCard).mockResolvedValue({
      ...article,
      title: "A considered headline",
      title_entities: [],
      abstract_entities: [],
    } as never);
    vi.mocked(trackEvent).mockResolvedValue({
      ok: true,
      event_type: "detail_view",
      profile_updated: false,
      behavior_score: null,
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("pagehide 与卸载只提交一次达到阈值的可见停留", async () => {
    const rendered = renderPage();
    await screen.findByText("A considered headline");

    now = 12_400;
    window.dispatchEvent(new Event("pagehide"));

    expect(sendTrackedEventKeepalive).toHaveBeenCalledWith({
      event_id: "dwell-7004:N301:route-load-1",
      user_id: 7004,
      event_type: "dwell",
      surface: "article_detail",
      news_id: "N301",
      dwell_ms: 12_400,
    });
    rendered.unmount();
    expect(sendTrackedEventKeepalive).toHaveBeenCalledTimes(1);
  });

  it("隐藏期间暂停，累计不足十秒时不提交", async () => {
    const rendered = renderPage();
    await screen.findByText("A considered headline");

    now = 4_000;
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
    document.dispatchEvent(new Event("visibilitychange"));
    now = 40_000;
    rendered.unmount();

    expect(sendTrackedEventKeepalive).not.toHaveBeenCalled();
  });

  it("投递异常不阻塞页面卸载", async () => {
    vi.mocked(sendTrackedEventKeepalive).mockImplementationOnce(() => {
      throw new Error("delivery rejected");
    });
    renderPage();
    await screen.findByText("A considered headline");
    now = 11_000;

    expect(() => window.dispatchEvent(new Event("pagehide"))).not.toThrow();
    await waitFor(() => expect(screen.getByText("A considered headline")).toBeInTheDocument());
  });
});
