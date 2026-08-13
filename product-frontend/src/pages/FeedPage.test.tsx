import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import FeedPage from "./FeedPage";
import { getFeed, trackEvent } from "../api/client";

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
  return { ...actual, useLocation: () => ({ key: "route-test" }) };
});

vi.mock("../api/client", () => ({
  getFeed: vi.fn(),
  stableClientId: vi.fn(() => "feed-load-test"),
  trackEvent: vi.fn(),
}));

vi.mock("../components/PostCard", () => ({
  default: ({ item }: { item: { article_id: number } }) => (
    <div data-testid={`article-${item.article_id}`}>{item.article_id}</div>
  ),
}));

const feedItems = [
  {
    article_id: 301,
    headline: "First",
    abstract: "First article",
    source_domain: "news.example.com",
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
    article_id: 302,
    headline: "Second",
    abstract: "Second article",
    source_domain: "sports.example.com",
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

describe("FeedPage impressions", () => {
  beforeEach(() => {
    personaState.selectedPersona.user_id = 7248;
    personaState.refreshTick = 0;
    vi.mocked(getFeed).mockResolvedValue({
      user_id: 7248,
      request_id: "feed-request-1",
      items: feedItems,
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
    expect(getFeed).toHaveBeenCalledWith(7248, 10, true, "feed-load-test");
    expect(trackEvent).toHaveBeenCalledWith(
      expect.objectContaining({
        event_id: "imp-7248:feed-request-1:301",
        user_id: 7248,
        article_id: 301,
        request_id: "feed-request-1",
      }),
    );
    expect(trackEvent).toHaveBeenCalledWith(
      expect.objectContaining({
        event_id: "imp-7248:feed-request-1:302",
        user_id: 7248,
        article_id: 302,
        request_id: "feed-request-1",
      }),
    );
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
    });
    rendered.rerender(<FeedPage />);

    await waitFor(() => expect(trackEvent).toHaveBeenCalledTimes(4));
    expect(trackEvent).toHaveBeenCalledWith(
      expect.objectContaining({
        event_id: "imp-1026:feed-request-2:301",
        user_id: 1026,
        article_id: 301,
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
    });
    await waitFor(() =>
      expect(trackEvent).toHaveBeenCalledWith(
        expect.objectContaining({ user_id: 1026, article_id: 301 }),
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
    });

    render(<FeedPage />);

    await waitFor(() =>
      expect(trackEvent).toHaveBeenCalledWith(
        expect.objectContaining({
          article_id: 301,
          sponsored_delivery_id: "ad-delivery-1",
        }),
      ),
    );
  });
});
