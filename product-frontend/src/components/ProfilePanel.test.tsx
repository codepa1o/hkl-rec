import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getProfile, resetProfile } from "../api/client";
import type { ProfileResponse } from "../api/types";
import ProfilePanel from "./ProfilePanel";

vi.mock("../api/client", () => ({
  getProfile: vi.fn(),
  resetProfile: vi.fn(),
}));

const profile: ProfileResponse = {
  source_space: "mind",
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
  it.each(["mind", "live"] as const)("%s 大于 1 的分数按组归一化且展开不改变占比", async (sourceSpace) => {
    const interests = profile.short_term.interests.map((topic, index) => ({...topic, score: [6,4,3,3,2,2][index]}));
    vi.mocked(getProfile).mockResolvedValue({...profile, source_space: sourceSpace,
      short_term: {...profile.short_term, interests},
      long_term: {...profile.long_term, interests: [{...profile.long_term.interests[0], score: 10}]},
    });
    render(<ProfilePanel sourceSpace={sourceSpace} userId={7004} refreshTick={0} onReset={vi.fn()} />);
    const short = within(await screen.findByRole("region", {name: "短期兴趣"}));
    expect(short.getByText("30%")).toBeInTheDocument();
    const card = short.getByText("短期主题 1").closest("article")!;
    expect(card.querySelector(".zr-profile-topic__track > span")).toHaveStyle({width: "30%"});
    fireEvent.click(short.getByRole("button", {name: "展开短期兴趣"}));
    expect(short.getByText("30%")).toBeInTheDocument();
    expect(short.getAllByText("10%")).toHaveLength(2);
    const long = within(screen.getByRole("region", {name: "长期兴趣"}));
    expect(long.getByText("100%")).toBeInTheDocument();
    expect(within(screen.getByRole("region", {name: "减少推荐"})).getByText("100%")).toBeInTheDocument();
    expect(screen.queryByText("600%")).not.toBeInTheDocument();
    expect(interests[0].score).toBe(6);
  });

  it("使用后端全量分母而非截断后的十个主题计算占比", async () => {
    vi.mocked(getProfile).mockResolvedValue({...profile, short_term: {
      ...profile.short_term, positive_score_total: 40,
      interests: [{...profile.short_term.interests[0], score: 6}],
    }});
    render(<ProfilePanel sourceSpace="mind" userId={7004} refreshTick={0} onReset={vi.fn()} />);
    expect(await screen.findByText("15%")).toBeInTheDocument();
  });

  it("零分数或非有限分数不产生 NaN 或无限百分比", async () => {
    vi.mocked(getProfile).mockResolvedValue({...profile, short_term: {...profile.short_term,
      interests: profile.short_term.interests.slice(0,3).map((topic,index) => ({...topic, score: [0, Number.NaN, Infinity][index]})),
    }});
    render(<ProfilePanel sourceSpace="mind" userId={7004} refreshTick={0} onReset={vi.fn()} />);
    const short = within(await screen.findByRole("region", {name: "短期兴趣"}));
    expect(short.getAllByText("0%")).toHaveLength(3);
  });
  afterEach(() => vi.useRealTimers());

  it("Live 有界刷新并在切换空间时取消后续请求", async () => {
    vi.useFakeTimers();
    vi.mocked(getProfile).mockResolvedValue({ ...profile, source_space: "live" });
    const view = render(<ProfilePanel sourceSpace="live" userId={7004} refreshTick={0} onReset={vi.fn()} />);
    await act(async () => {});
    expect(screen.getByText("63% 画像积累度")).toBeInTheDocument();
    for (let i = 0; i < 8; i += 1) {
      await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    }
    expect(getProfile).toHaveBeenCalledTimes(6);
    view.rerender(<ProfilePanel sourceSpace="live" userId={7004} refreshTick={1} onReset={vi.fn()} />);
    await act(async () => {});
    vi.mocked(getProfile).mockResolvedValue(profile);
    view.rerender(<ProfilePanel sourceSpace="mind" userId={7004} refreshTick={1} onReset={vi.fn()} />);
    await act(async () => {});
    const calls = vi.mocked(getProfile).mock.calls.length;
    await act(async () => { await vi.advanceTimersByTimeAsync(20000); });
    expect(getProfile).toHaveBeenCalledTimes(calls);
    view.unmount();
  });
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
    render(
      <ProfilePanel
        sourceSpace="mind"
        userId={7004}
        refreshTick={0}
        onReset={vi.fn()}
      />,
    );

    await waitFor(() => expect(screen.getByText("持续学习")).toBeInTheDocument());
    expect(screen.getByText("63% 置信度")).toBeInTheDocument();
    expect(screen.getByText("短期兴趣")).toBeInTheDocument();
    expect(screen.getByText("长期兴趣")).toBeInTheDocument();
    expect(screen.getByText("减少推荐")).toBeInTheDocument();
    expect(screen.getAllByText(/推荐点击 2 次/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/深度阅读 1 次/).length).toBeGreaterThan(0);
    expect(screen.getByText(/点踩 2 次/)).toBeInTheDocument();
    expect(getProfile).toHaveBeenCalledWith("mind", 7004);
  });

  it("默认仅展示前五项并允许展开", async () => {
    render(<ProfilePanel sourceSpace="mind" userId={7004} refreshTick={0} onReset={vi.fn()} />);
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

    render(<ProfilePanel sourceSpace="mind" userId={7004} refreshTick={0} onReset={vi.fn()} />);

    expect(await screen.findByText("刚开始了解你")).toBeInTheDocument();
    expect(screen.getByText(/阅读、搜索、停留或点踩后/)).toBeInTheDocument();
  });

  it("页面模式提供独立页样式钩子", async () => {
    render(
      <ProfilePanel
        sourceSpace="mind"
        userId={7004}
        refreshTick={0}
        onReset={vi.fn()}
        variant="page"
      />,
    );

    const heading = await screen.findByRole("heading", { name: "我的兴趣画像" });
    expect(heading.closest(".zr-profile-panel")).toHaveClass("zr-profile-panel--page");
  });

  it("实时空间没有主题时仍展示独立的最近活动", async () => {
    vi.mocked(getProfile).mockResolvedValue({
      ...profile,
      source_space: "live",
      status: "learning",
      short_term: { interests: [], reduced_topics: [] },
      long_term: { interests: [], reduced_topics: [] },
      recent_clicked_news: [
        {
          news_id: "L0123456789abcdef0123456789abcdef",
          title: "Live briefing",
          click_ts: 1_786_838_400,
        },
      ],
    });

    render(
      <MemoryRouter>
        <ProfilePanel
          sourceSpace="live"
          userId={7004}
          refreshTick={0}
          onReset={vi.fn()}
        />
      </MemoryRouter>,
    );

    expect(await screen.findByText("最近活动")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Live briefing" })).toHaveAttribute(
      "href",
      "/articles/live/L0123456789abcdef0123456789abcdef",
    );
    expect(screen.queryByText("短期兴趣")).not.toBeInTheDocument();
  });

  it("重置需要二次确认，成功后更新画像并刷新信息流", async () => {
    const onReset = vi.fn();
    vi.mocked(getProfile).mockResolvedValue({ ...profile, source_space: "live" });
    vi.mocked(resetProfile).mockResolvedValue({
      ...profile,
      source_space: "live",
      status: "cold",
      confidence: 0,
      evidence_count: 0,
      short_term: { interests: [], reduced_topics: [] },
      long_term: { interests: [], reduced_topics: [] },
    });
    render(
      <ProfilePanel sourceSpace="live" userId={7004} refreshTick={0} onReset={onReset} />,
    );
    await screen.findByText("持续学习");

    fireEvent.click(screen.getByRole("button", { name: "重置画像" }));
    expect(resetProfile).not.toHaveBeenCalled();
    expect(screen.getByText("此操作会恢复冷启动画像，历史事件仍会保留。")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "确认重置" }));

    await waitFor(() => expect(resetProfile).toHaveBeenCalledTimes(1));
    expect(resetProfile).toHaveBeenCalledWith("live", 7004);
    await waitFor(() => expect(screen.getByText("刚开始了解你")).toBeInTheDocument());
    expect(onReset).toHaveBeenCalledTimes(1);
  });

  it("重置失败后显示本地化错误并允许重试", async () => {
    vi.mocked(resetProfile).mockRejectedValueOnce(new Error("Request failed"));
    render(<ProfilePanel sourceSpace="mind" userId={7004} refreshTick={0} onReset={vi.fn()} />);
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
    render(<ProfilePanel sourceSpace="mind" userId={7004} refreshTick={0} onReset={vi.fn()} />);
    await screen.findByText("持续学习");

    fireEvent.click(screen.getByRole("button", { name: "重置画像" }));
    fireEvent.click(screen.getByRole("button", { name: "确认重置" }));

    expect(screen.getByRole("button", { name: "正在重置…" })).toBeDisabled();
    resolveReset?.(profile);
    await waitFor(() => expect(screen.queryByText("正在重置…")).not.toBeInTheDocument());
  });
});
