import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { FeedItem } from "../api/types";
import { trackEvent } from "../api/client";
import PostCard from "./PostCard";

vi.mock("../api/client", () => ({ trackEvent: vi.fn().mockResolvedValue({ ok: true }) }));

const sponsoredItem: FeedItem = {
  news_id: "N301",
  title: "Sponsored finance briefing",
  abstract: "A sponsored news summary.",
  url: "https://finance.example.com/301",
  source_domain: "finance.example.com",
  category: "finance",
  subcategory: "markets",
  categories: [{ topic_id: 1, display_name: "Finance" }],
  selected_reason: "Selected because its categories match the user profile.",
  scores: {
    base_recall_score: 0,
    personalized_topic_score: 0,
    default_topic_score: 0,
    topic_match_score: 0,
    query_recall_boost: 0,
    final_score: 225,
    sponsored_score: 225,
  },
  recall_sources: ["sponsored"],
  is_fallback: false,
  content_type: "sponsored",
  sponsored: {
    delivery_id: "ad-delivery-1",
    campaign_id: 9001,
    creative_id: 19001,
    label: "Sponsored",
  },
};

describe("PostCard", () => {
  beforeEach(() => {
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText: vi.fn().mockResolvedValue(undefined) },
    });
  });

  it("用中文显示界面元素和动态标签，同时保留英文新闻内容", () => {
    render(
      <MemoryRouter>
        <PostCard item={sponsoredItem} userId={7248} showReason />
      </MemoryRouter>,
    );

    expect(screen.getAllByText("财经")).toHaveLength(2);
    expect(screen.getByText("赞助内容")).toBeInTheDocument();
    expect(screen.getByText("来源：finance.example.com")).toBeInTheDocument();
    expect(screen.getByText("文章分类与当前用户画像相匹配。")).toBeInTheDocument();
    expect(screen.getByText("查看详情")).toBeInTheDocument();
    expect(screen.getByText("分享")).toBeInTheDocument();
    expect(screen.getByText("Sponsored finance briefing")).toBeInTheDocument();
    expect(screen.getByText("A sponsored news summary.")).toBeInTheDocument();
  });

  it("分享按钮复制文章链接并记录分享行为", async () => {
    render(
      <MemoryRouter>
        <PostCard item={sponsoredItem} userId={7248} requestId="feed-1" />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: "分享文章" }));

    await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalled());
    expect(trackEvent).toHaveBeenCalledWith(
      expect.objectContaining({
        user_id: 7248,
        news_id: "N301",
        event_type: "share",
        request_id: "feed-1",
      }),
    );
  });
});
