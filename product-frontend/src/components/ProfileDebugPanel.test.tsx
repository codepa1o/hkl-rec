import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { getDebugProfile } from "../api/client";
import type { DebugProfileResponse } from "../api/types";
import ProfileDebugPanel from "./ProfileDebugPanel";

vi.mock("../api/client", () => ({
  getDebugProfile: vi.fn(),
}));
vi.mock("./TopicWeightChart", () => ({
  default: () => <div aria-label="主题权重柱状图" />,
}));

const profileWithRecentReading = {
  user_id: 7248,
  cold_start_seed_key: "cold_start_default",
  behavior_score: 32,
  topic_weights: [],
  recent_clicked_news: [
    {
      news_id: "N1003",
      title: "Finance briefing",
      click_ts: 1_786_838_400,
    },
  ],
  recent_queries: [],
  vector_summary: {
    vector_key_count: 0,
    top_contributing_topics: [],
  },
} as unknown as DebugProfileResponse;

describe("ProfileDebugPanel", () => {
  beforeEach(() => {
    vi.mocked(getDebugProfile).mockResolvedValue(profileWithRecentReading);
  });

  it("将画像数据表达为用户兴趣，不泄露工程调试字段", async () => {
    vi.mocked(getDebugProfile).mockResolvedValue({
      ...profileWithRecentReading,
      cold_start_seed_key: "tech_seed",
      behavior_score: 12.5,
      topic_weights: [{ topic_id: 1, weight: 0.8 }],
      vector_summary: { vector_key_count: 24, top_contributing_topics: [] },
    });

    render(
      <MemoryRouter>
        <ProfileDebugPanel userId={7248} refreshTick={0} />
      </MemoryRouter>,
    );

    await waitFor(() => expect(screen.getByText("你的兴趣")).toBeInTheDocument());
    expect(getDebugProfile).toHaveBeenCalledWith(7248);
    expect(screen.getByText("兴趣活跃度")).toBeInTheDocument();
    expect(screen.getByText("最近阅读")).toBeInTheDocument();
    expect(screen.queryByText("冷启动种子")).not.toBeInTheDocument();
    expect(screen.queryByText("向量维度数")).not.toBeInTheDocument();
    expect(screen.queryByText("用户画像调试")).not.toBeInTheDocument();
  });

  it("仅将最近阅读标题渲染为可跳转的详情链接", async () => {
    render(
      <MemoryRouter>
        <ProfileDebugPanel userId={7248} refreshTick={0} />
      </MemoryRouter>,
    );

    const titleLink = await screen.findByRole("link", { name: "Finance briefing" });
    expect(titleLink).toHaveAttribute("href", "/articles/N1003");
    expect(screen.queryByText("新闻 N1003")).not.toBeInTheDocument();

    const date = screen.getByText(/2026/);
    expect(date.closest("a")).toBeNull();
  });

  it("展示全部最近阅读记录而不是只截取前四条", async () => {
    vi.mocked(getDebugProfile).mockResolvedValue({
      ...profileWithRecentReading,
      recent_clicked_news: Array.from({ length: 7 }, (_, index) => ({
        news_id: `N${1001 + index}`,
        title: `新闻标题 ${index + 1}`,
        click_ts: 1_786_838_400 - index,
      })),
    });

    render(
      <MemoryRouter>
        <ProfileDebugPanel userId={7248} refreshTick={0} />
      </MemoryRouter>,
    );

    expect(await screen.findAllByRole("link")).toHaveLength(7);
    expect(screen.getByRole("link", { name: "新闻标题 7" })).toBeInTheDocument();
  });
});
