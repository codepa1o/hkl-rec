import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ensureArticleContent,
  getArticleCard,
  newClientId,
  sendTrackedEventKeepalive,
  trackEvent,
} from "../api/client";
import ArticleDetailPage from "./ArticleDetailPage";

const bumpProfile = vi.fn();
const selectSourceSpace = vi.fn();

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

vi.mock("../context/SourceSpaceContext", () => ({
  useSourceSpace: () => ({ selectSourceSpace }),
}));

vi.mock("../api/client", () => ({
  ensureArticleContent: vi.fn(),
  getArticleCard: vi.fn(),
  newClientId: vi.fn(),
  sendTrackedEventKeepalive: vi.fn(),
  trackEvent: vi.fn(),
}));

const article = {
  source_space: "mind" as const,
  article_id: "N301",
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

function renderPage(path = "/articles/mind/N301") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route
          path="/articles/:sourceSpace/:articleId"
          element={<ArticleDetailPage />}
        />
        <Route path="/articles/:newsId" element={<ArticleDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.mocked(ensureArticleContent).mockResolvedValue({
    article_id: "N301",
    status: "blocked",
    enqueued: false,
    retry_after_seconds: null,
  });
});

describe("ArticleDetailPage entities", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(newClientId).mockReturnValue("route-load-1");
    vi.mocked(getArticleCard).mockResolvedValue(article as never);
    vi.mocked(ensureArticleContent).mockResolvedValue({
      article_id: "N301",
      status: "blocked",
      enqueued: false,
      retry_after_seconds: null,
    });
    vi.mocked(trackEvent).mockResolvedValue({
      ok: true,
      event_type: "detail_view",
      source_space: "mind",
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
      source_space: "mind",
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
      event_id: "dwell-mind:7004:N301:route-load-1",
      user_id: 7004,
      source_space: "mind",
      event_type: "dwell",
      surface: "article_detail",
      article_id: "N301",
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

describe("ArticleDetailPage live metadata", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(newClientId).mockReturnValue("route-load-live");
    vi.mocked(trackEvent).mockResolvedValue({
      ok: true,
      event_type: "detail_view",
      source_space: "live",
      profile_updated: false,
      behavior_score: null,
    });
    vi.mocked(getArticleCard).mockResolvedValue({
      ...article,
      source_space: "live",
      article_id: "L0123456789abcdef0123456789abcdef",
      news_id: null,
      title: "Live article",
      publisher: "Reuters",
      language: "en",
      image_url: "https://example.com/live.jpg",
      published_at: "2026-08-18T08:00:00Z",
      title_entities: [],
      abstract_entities: [],
    });
  });

  it("展示实时元数据并仅记录原文跳转，不刷新画像", async () => {
    renderPage("/articles/live/L0123456789abcdef0123456789abcdef");

    const original = await screen.findByRole("link", { name: "阅读原文" });
    expect(original).toHaveAttribute("target", "_blank");
    expect(original).toHaveAttribute("rel", expect.stringContaining("noopener"));
    expect(screen.getByText(/Reuters/)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Live article" })).toBeInTheDocument();

    await waitFor(() => expect(bumpProfile).toHaveBeenCalledTimes(1));
    const bumpsBeforeOutbound = bumpProfile.mock.calls.length;
    fireEvent.click(original);
    await waitFor(() =>
      expect(trackEvent).toHaveBeenCalledWith(
        expect.objectContaining({
          source_space: "live",
          article_id: "L0123456789abcdef0123456789abcdef",
          event_type: "outbound_click",
        }),
      ),
    );
    expect(bumpProfile).toHaveBeenCalledTimes(bumpsBeforeOutbound);
  });

  it("拒绝来源与文章编号不匹配的路由", () => {
    renderPage("/articles/live/N301");
    expect(screen.getByText("文章编号无效。")).toBeInTheDocument();
    expect(getArticleCard).not.toHaveBeenCalled();
  });
});

describe("ArticleDetailPage feed return navigation", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(newClientId).mockReturnValue("route-load-return");
    vi.mocked(getArticleCard).mockResolvedValue(article as never);
    vi.mocked(trackEvent).mockResolvedValue({
      ok: true,
      event_type: "detail_view",
      source_space: "mind",
      profile_updated: false,
      behavior_score: null,
    });
  });

  it("marks the return action as sticky article navigation", async () => {
    renderPage();

    await screen.findByText(article.title);

    expect(screen.getByRole("button", { name: "返回信息流" })).toHaveClass(
      "zr-back-link",
      "zr-back-link--sticky",
    );
  });

  it("uses browser history when the article was opened from a feed", async () => {
    render(
      <MemoryRouter
        initialIndex={1}
        initialEntries={[
          "/?category=sports",
          {
            pathname: "/articles/mind/N301",
            state: {
              fromFeed: true,
              feedContextKey: '["mind",7004,"sports","all"]',
            },
          },
        ]}
      >
        <Routes>
          <Route path="/" element={<div>restored-feed-route</div>} />
          <Route
            path="/articles/:sourceSpace/:articleId"
            element={<ArticleDetailPage />}
          />
        </Routes>
      </MemoryRouter>,
    );

    await screen.findByText(article.title);
    fireEvent.click(screen.getByRole("button", { name: "返回信息流" }));

    expect(await screen.findByText("restored-feed-route")).toBeInTheDocument();
  });

  it("falls back to the article source home for a direct detail visit", async () => {
    render(
      <MemoryRouter initialEntries={["/articles/mind/N301"]}>
        <Routes>
          <Route path="/" element={<div>source-home</div>} />
          <Route
            path="/articles/:sourceSpace/:articleId"
            element={<ArticleDetailPage />}
          />
        </Routes>
      </MemoryRouter>,
    );

    await screen.findByText(article.title);
    fireEvent.click(screen.getByRole("button", { name: "返回信息流" }));

    expect(selectSourceSpace).toHaveBeenCalledWith("mind");
    expect(await screen.findByText("source-home")).toBeInTheDocument();
  });
});
