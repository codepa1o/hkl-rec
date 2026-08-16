import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { getProfile, resetProfile } from "../api/client";
import type { ProfileResponse } from "../api/types";
import ProfilePanel from "./ProfilePanel";

vi.mock("../api/client", () => ({
  getProfile: vi.fn(),
  resetProfile: vi.fn(),
}));

const profile: ProfileResponse = {
  user_id: 7004,
  profile_version: "v2",
  status: "learning",
  confidence: 0.625,
  evidence_count: 8,
  short_term: {
    interests: Array.from({ length: 6 }, (_, index) => ({
      topic_id: index + 1,
      display_name: `短期主题 ${index + 1}`,
      score: 0.9 - index * 0.05,
      positive_score: 1,
      negative_score: 0.1,
      positive_evidence_count: 3,
      negative_evidence_count: 1,
      signal_counts: { recommendation_click: 2, dwell: 1 },
      last_signal_type: "dwell",
      last_event_ts: 1_700_000_000,
    })),
    reduced_topics: [
      {
        topic_id: 99,
        display_name: "减少推荐的主题",
        score: -0.7,
        positive_score: 0,
        negative_score: 0.7,
        positive_evidence_count: 0,
        negative_evidence_count: 2,
        signal_counts: { downvote: 2 },
        last_signal_type: "downvote",
        last_event_ts: 1_700_000_100,
      },
    ],
  },
  long_term: {
    interests: [
      {
        topic_id: 7,
        display_name: "长期主题",
        score: 0.8,
        positive_score: 0.8,
        negative_score: 0,
        positive_evidence_count: 5,
        negative_evidence_count: 0,
        signal_counts: { upvote: 3, search_result_click: 2 },
        last_signal_type: "upvote",
        last_event_ts: 1_700_000_200,
      },
    ],
    reduced_topics: [],
  },
  recent_clicked_news: [],
  recent_queries: [],
  last_updated_at: "2026-08-16T12:00:00Z",
};

describe("ProfilePanel", () => {
  beforeEach(() => {
    vi.mocked(getProfile).mockResolvedValue(profile);
    vi.mocked(resetProfile).mockResolvedValue({
      ...profile,
      status: "cold",
      confidence: 0,
      evidence_count: 0,
      short_term: { interests: [], reduced_topics: [] },
      long_term: { interests: [], reduced_topics: [] },
    });
  });

  it("展示置信度、短长期主题与本地化证据解释", async () => {
    render(<ProfilePanel refreshTick={0} onReset={vi.fn()} />);

    await waitFor(() => expect(screen.getByText("持续学习")).toBeInTheDocument());
    expect(screen.getByText("63% 置信度")).toBeInTheDocument();
    expect(screen.getByText("短期兴趣")).toBeInTheDocument();
    expect(screen.getByText("长期兴趣")).toBeInTheDocument();
    expect(screen.getByText("减少推荐")).toBeInTheDocument();
    expect(screen.getAllByText(/推荐点击 2 次/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/深度阅读 1 次/).length).toBeGreaterThan(0);
    expect(screen.getByText(/点踩 2 次/)).toBeInTheDocument();
    expect(getProfile).toHaveBeenCalledWith();
  });

  it("默认仅展示前五项并允许展开", async () => {
    render(<ProfilePanel refreshTick={0} onReset={vi.fn()} />);
    await screen.findByText("短期主题 1");

    expect(screen.queryByText("短期主题 6")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "展开短期兴趣" }));
    expect(screen.getByText("短期主题 6")).toBeInTheDocument();
  });

  it("空画像给出冷启动说明", async () => {
    vi.mocked(getProfile).mockResolvedValue({
      ...profile,
      status: "cold",
      confidence: 0,
      evidence_count: 0,
      short_term: { interests: [], reduced_topics: [] },
      long_term: { interests: [], reduced_topics: [] },
    });

    render(<ProfilePanel refreshTick={0} onReset={vi.fn()} />);

    expect(await screen.findByText("刚开始了解你")).toBeInTheDocument();
    expect(screen.getByText(/阅读、搜索、停留或点踩后/)).toBeInTheDocument();
  });

  it("页面模式提供独立页样式钩子", async () => {
    render(<ProfilePanel refreshTick={0} onReset={vi.fn()} variant="page" />);

    const heading = await screen.findByRole("heading", { name: "我的兴趣画像" });
    expect(heading.closest(".zr-profile-panel")).toHaveClass("zr-profile-panel--page");
  });

  it("重置需要二次确认，成功后更新画像并刷新信息流", async () => {
    const onReset = vi.fn();
    render(<ProfilePanel refreshTick={0} onReset={onReset} />);
    await screen.findByText("持续学习");

    fireEvent.click(screen.getByRole("button", { name: "重置画像" }));
    expect(resetProfile).not.toHaveBeenCalled();
    expect(screen.getByText("此操作会恢复冷启动画像，历史事件仍会保留。")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "确认重置" }));

    await waitFor(() => expect(resetProfile).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByText("刚开始了解你")).toBeInTheDocument());
    expect(onReset).toHaveBeenCalledTimes(1);
  });

  it("重置失败后显示本地化错误并允许重试", async () => {
    vi.mocked(resetProfile).mockRejectedValueOnce(new Error("Request failed"));
    render(<ProfilePanel refreshTick={0} onReset={vi.fn()} />);
    await screen.findByText("持续学习");

    fireEvent.click(screen.getByRole("button", { name: "重置画像" }));
    fireEvent.click(screen.getByRole("button", { name: "确认重置" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("请求失败");
    expect(screen.getByRole("button", { name: "确认重置" })).toBeEnabled();
  });

  it("重置提交期间锁定确认操作", async () => {
    let resolveReset: ((value: ProfileResponse) => void) | undefined;
    vi.mocked(resetProfile).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveReset = resolve;
        }),
    );
    render(<ProfilePanel refreshTick={0} onReset={vi.fn()} />);
    await screen.findByText("持续学习");

    fireEvent.click(screen.getByRole("button", { name: "重置画像" }));
    fireEvent.click(screen.getByRole("button", { name: "确认重置" }));

    expect(screen.getByRole("button", { name: "正在重置…" })).toBeDisabled();
    resolveReset?.(profile);
    await waitFor(() => expect(screen.queryByText("正在重置…")).not.toBeInTheDocument());
  });
});
