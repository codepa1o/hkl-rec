import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import FeedPage from "./FeedPage";
import { getFeed, trackEvent } from "../api/client";

const routeState = vi.hoisted(() => ({ key: "route-test", search: "" }));

const personaState = {
  selectedPersona: {
    user_id: 7248,
    display_name: "Backend Explorer",
    behavior_score: 0,
    top_topics: [],
  },
  refreshTick: 0,
  bumpProfile: vi.fn(),
};

vi.mock("../context/PersonaContext", () => ({
  usePersona: () => personaState,
}));

vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return { ...actual, useLocation: () => routeState };
});

vi.mock("../api/client", () => ({
  getFeed: vi.fn(),
  newClientId: vi.fn(() => "feed-page-test"),
  stableClientId: vi.fn(() => "feed-load-test"),
  trackEvent: vi.fn(),
}));

vi.mock("../components/PostCard", () => ({
  default: ({ item }: { item: { news_id: string } }) => (
    <div data-testid={`article-${item.news_id}`}>{item.news_id}</div>
  ),
}));

const feedItems = [
  {
    news_id: "N301",
    title: "First",
    abstract: "First article",
    url: "https://news.example.com/301",
    source_domain: "news.example.com",
    category: "news",
    subcategory: "local",
    categories: [],
    selected_reason: "Profile",
    scores: {
      base_recall_score: 1,
      personalized_topic_score: 1,
      default_topic_score: 0,
      topic_match_score: 1,
      query_recall_boost: 0,
      final_score: 1,
    },
    recall_sources: ["profile_topic"],
    is_fallback: false,
    content_type: "organic" as const,
  },
  {
    news_id: "N302",
    title: "Second",
    abstract: "Second article",
    url: "https://sports.example.com/302",
    source_domain: "sports.example.com",
    category: "sports",
    subcategory: "football",
    categories: [],
    selected_reason: "Profile",
    scores: {
      base_recall_score: 0.9,
      personalized_topic_score: 0.9,
      default_topic_score: 0,
      topic_match_score: 0.9,
      query_recall_boost: 0,
      final_score: 0.9,
    },
    recall_sources: ["profile_topic"],
    is_fallback: false,
    content_type: "organic" as const,
  },
];

const thirdFeedItem = {
  ...feedItems[0],
  news_id: "N303",
  title: "Third",
  abstract: "Third article",
  url: "https://science.example.com/303",
};

let intersectionCallback: IntersectionObserverCallback | null = null;

class TestIntersectionObserver {
  readonly root = null;
  readonly rootMargin = "800px 0px";
  readonly thresholds = [0];

  constructor(callback: IntersectionObserverCallback) {
    intersectionCallback = callback;
  }

  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords(): IntersectionObserverEntry[] {
    return [];
  }
}

describe("FeedPage impressions", () => {
  beforeEach(() => {
    personaState.selectedPersona.user_id = 7248;
    personaState.refreshTick = 0;
    routeState.search = "";
    intersectionCallback = null;
    vi.stubGlobal("IntersectionObserver", TestIntersectionObserver);
    vi.mocked(getFeed).mockResolvedValue({
      user_id: 7248,
      request_id: "feed-request-1",
      items: feedItems,
      next_cursor: null,
      has_more: false,
    });
    vi.mocked(trackEvent).mockResolvedValue({
      ok: true,
      event_type: "feed_impression",
      profile_updated: false,
      behavior_score: null,
    });
  });

  it("records one article-scoped impression for each item", async () => {
    render(<FeedPage />);

    await waitFor(() => expect(trackEvent).toHaveBeenCalledTimes(2));
    expect(getFeed).toHaveBeenCalledWith(
      7248,
      20,
      true,
      "feed-load-test",
      undefined,
      undefined,
    );
    expect(trackEvent).toHaveBeenCalledWith(
      expect.objectContaining({
        event_id: "imp-7248:feed-request-1:N301",
        user_id: 7248,
        news_id: "N301",
        request_id: "feed-request-1",
      }),
    );
    expect(trackEvent).toHaveBeenCalledWith(
      expect.objectContaining({
        event_id: "imp-7248:feed-request-1:N302",
        user_id: 7248,
        news_id: "N302",
        request_id: "feed-request-1",
      }),
    );
  });

  it("按 URL 分类请求个性化信息流并显示中文标题", async () => {
    routeState.search = "?category=sports";

    render(<FeedPage />);

    await waitFor(() =>
      expect(getFeed).toHaveBeenCalledWith(
        7248,
        20,
        true,
        "feed-load-test",
        undefined,
        "sports",
      ),
    );
    expect(screen.getByRole("heading", { name: "体育新闻" })).toBeInTheDocument();
    expect(screen.getByText("在体育分类内，根据你的阅读兴趣持续推荐")).toBeInTheDocument();
  });

  it("只呈现真实的个性化信息流，不展示未接入后端的伪排序", async () => {
    render(<FeedPage />);

    expect(screen.getByRole("heading", { name: "为你推荐" })).toBeInTheDocument();
    expect(screen.getByText("根据你的阅读兴趣持续更新")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "最佳" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "热门" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "最新" })).not.toBeInTheDocument();
    await waitFor(() => expect(trackEvent).toHaveBeenCalledTimes(2));
  });

  it("tracks the same articles again for a different persona", async () => {
    const rendered = render(<FeedPage />);
    await waitFor(() => expect(trackEvent).toHaveBeenCalledTimes(2));

    personaState.selectedPersona.user_id = 1026;
    personaState.refreshTick += 1;
    vi.mocked(getFeed).mockResolvedValue({
      user_id: 1026,
      request_id: "feed-request-2",
      items: feedItems,
      next_cursor: null,
      has_more: false,
    });
    rendered.rerender(<FeedPage />);

    await waitFor(() => expect(trackEvent).toHaveBeenCalledTimes(4));
    expect(trackEvent).toHaveBeenCalledWith(
      expect.objectContaining({
        event_id: "imp-1026:feed-request-2:N301",
        user_id: 1026,
        news_id: "N301",
      }),
    );
  });

  it("does not attribute the previous persona's slate during a switch", async () => {
    let resolveSecond:
      | ((value: Awaited<ReturnType<typeof getFeed>>) => void)
      | undefined;
    const rendered = render(<FeedPage />);
    await waitFor(() => expect(trackEvent).toHaveBeenCalledTimes(2));

    personaState.selectedPersona.user_id = 1026;
    personaState.refreshTick += 1;
    vi.mocked(getFeed).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveSecond = resolve;
        }),
    );
    vi.mocked(trackEvent).mockClear();

    rendered.rerender(<FeedPage />);

    await waitFor(() => expect(getFeed).toHaveBeenCalledTimes(2));
    expect(trackEvent).not.toHaveBeenCalled();
    resolveSecond?.({
      user_id: 1026,
      request_id: "feed-request-2",
      items: feedItems,
      next_cursor: null,
      has_more: false,
    });
    await waitFor(() =>
      expect(trackEvent).toHaveBeenCalledWith(
        expect.objectContaining({ user_id: 1026, news_id: "N301" }),
      ),
    );
  });

  it("includes sponsored delivery identity in impression tracking", async () => {
    vi.mocked(getFeed).mockResolvedValue({
      user_id: 7248,
      request_id: "feed-sponsored",
      items: [
        {
          ...feedItems[0],
          content_type: "sponsored",
          sponsored: {
            delivery_id: "ad-delivery-1",
            campaign_id: 9001,
            creative_id: 19001,
            label: "Sponsored",
          },
        },
      ],
      next_cursor: null,
      has_more: false,
    });

    render(<FeedPage />);

    await waitFor(() =>
      expect(trackEvent).toHaveBeenCalledWith(
        expect.objectContaining({
          news_id: "N301",
          sponsored_delivery_id: "ad-delivery-1",
        }),
      ),
    );
  });

  it("loads the next cursor page and appends only unseen news", async () => {
    vi.mocked(getFeed)
      .mockResolvedValueOnce({
        user_id: 7248,
        request_id: "feed-request-1",
        items: feedItems,
        next_cursor: "cursor-page-2",
        has_more: true,
      })
      .mockResolvedValueOnce({
        user_id: 7248,
        request_id: "feed-request-2",
        items: [feedItems[1], thirdFeedItem],
        next_cursor: null,
        has_more: false,
      });

    render(<FeedPage />);
    await waitFor(() => expect(intersectionCallback).not.toBeNull());

    act(() => {
      intersectionCallback?.(
        [{ isIntersecting: true } as IntersectionObserverEntry],
        {} as IntersectionObserver,
      );
    });

    await waitFor(() => expect(getFeed).toHaveBeenCalledTimes(2));
    expect(getFeed).toHaveBeenLastCalledWith(
      7248,
      20,
      true,
      "feed-page-test",
      "cursor-page-2",
      undefined,
    );
    expect(screen.getByTestId("article-N303")).toBeInTheDocument();
    expect(screen.getAllByTestId("article-N302")).toHaveLength(1);
    await waitFor(() =>
      expect(trackEvent).toHaveBeenCalledWith(
        expect.objectContaining({
          event_id: "imp-7248:feed-request-2:N303",
          request_id: "feed-request-2",
        }),
      ),
    );
    expect(screen.getByText("已加载 3 篇新闻")).toBeInTheDocument();
  });

  it("keeps loaded news and retries a failed next page", async () => {
    vi.mocked(getFeed)
      .mockResolvedValueOnce({
        user_id: 7248,
        request_id: "feed-request-1",
        items: feedItems,
        next_cursor: "cursor-page-2",
        has_more: true,
      })
      .mockRejectedValueOnce(new Error("temporary failure"))
      .mockResolvedValueOnce({
        user_id: 7248,
        request_id: "feed-request-2",
        items: [thirdFeedItem],
        next_cursor: null,
        has_more: false,
      });

    render(<FeedPage />);
    await waitFor(() => expect(intersectionCallback).not.toBeNull());
    act(() => {
      intersectionCallback?.(
        [{ isIntersecting: true } as IntersectionObserverEntry],
        {} as IntersectionObserver,
      );
    });

    const retry = await screen.findByRole("button", { name: "重新加载" });
    expect(screen.getByTestId("article-N301")).toBeInTheDocument();
    fireEvent.click(retry);

    expect(await screen.findByTestId("article-N303")).toBeInTheDocument();
    expect(getFeed).toHaveBeenCalledTimes(3);
  });

  it("分类切换后忽略上一个分类的迟到响应", async () => {
    let resolveSports:
      | ((value: Awaited<ReturnType<typeof getFeed>>) => void)
      | undefined;
    let resolveFinance:
      | ((value: Awaited<ReturnType<typeof getFeed>>) => void)
      | undefined;
    vi.mocked(getFeed)
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveSports = resolve;
          }),
      )
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            resolveFinance = resolve;
          }),
      );
    routeState.search = "?category=sports";
    const rendered = render(<FeedPage />);
    await waitFor(() => expect(getFeed).toHaveBeenCalledTimes(1));

    routeState.search = "?category=finance";
    rendered.rerender(<FeedPage />);
    await waitFor(() => expect(getFeed).toHaveBeenCalledTimes(2));

    resolveFinance?.({
      user_id: 7248,
      request_id: "finance-feed",
      items: [{ ...feedItems[0], news_id: "FIN-1", category: "finance" }],
      next_cursor: null,
      has_more: false,
    });
    expect(await screen.findByTestId("article-FIN-1")).toBeInTheDocument();

    resolveSports?.({
      user_id: 7248,
      request_id: "sports-feed",
      items: [{ ...feedItems[0], news_id: "SPORT-1", category: "sports" }],
      next_cursor: null,
      has_more: false,
    });
    await act(async () => Promise.resolve());

    expect(screen.queryByTestId("article-SPORT-1")).not.toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "财经新闻" })).toBeInTheDocument();
  });
});
