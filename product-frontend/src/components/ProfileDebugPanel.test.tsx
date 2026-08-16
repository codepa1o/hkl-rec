import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { getDebugProfile } from "../api/client";
import ProfileDebugPanel from "./ProfileDebugPanel";

vi.mock("../api/client", () => ({ getDebugProfile: vi.fn() }));
vi.mock("./TopicWeightChart", () => ({
  default: () => <div aria-label="主题权重柱状图" />,
}));

describe("ProfileDebugPanel", () => {
  it("将画像数据表达为用户兴趣，不泄露工程调试字段", async () => {
    vi.mocked(getDebugProfile).mockResolvedValue({
      user_id: 7248,
      cold_start_seed_key: "tech_seed",
      behavior_score: 12.5,
      topic_weights: [{ topic_id: 1, weight: 0.8 }],
      recent_clicked_articles: [{ article_id: 301, click_ts: 1_700_000_000 }],
      recent_queries: [],
      vector_summary: { vector_key_count: 24, top_contributing_topics: [] },
    });

    render(<ProfileDebugPanel userId={7248} refreshTick={0} />);

    await waitFor(() => expect(screen.getByText("你的兴趣")).toBeInTheDocument());
    expect(getDebugProfile).toHaveBeenCalledWith(7248);
    expect(screen.getByText("兴趣活跃度")).toBeInTheDocument();
    expect(screen.getByText("最近阅读")).toBeInTheDocument();
    expect(screen.queryByText("冷启动种子")).not.toBeInTheDocument();
    expect(screen.queryByText("向量维度数")).not.toBeInTheDocument();
    expect(screen.queryByText("用户画像调试")).not.toBeInTheDocument();
  });
});
