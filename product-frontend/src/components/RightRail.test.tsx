import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import RightRail from "./RightRail";

const state = {
  user: { user_id: 7004, email: "reader@example.com", display_name: "Reader" },
  selectedPersona: { user_id: 7004, display_name: "Reader", behavior_score: 0, top_topics: [] },
  refreshTick: 2,
  bumpProfile: vi.fn(),
};

vi.mock("../context/AuthContext", () => ({ useAuth: () => ({ user: state.user }) }));
vi.mock("../context/PersonaContext", () => ({
  usePersona: () => ({
    selectedPersona: state.selectedPersona,
    refreshTick: state.refreshTick,
    bumpProfile: state.bumpProfile,
  }),
}));
vi.mock("./ProfilePanel", () => ({
  default: () => <div>正式画像面板</div>,
}));
vi.mock("./ProfileDebugPanel", () => ({
  default: ({ userId }: { userId: number }) => <div>调试画像 {userId}</div>,
}));

describe("RightRail profile identity routing", () => {
  it("当前登录用户使用正式画像接口面板", () => {
    state.selectedPersona.user_id = 7004;
    render(<RightRail />);
    expect(screen.getByText("正式画像面板")).toBeInTheDocument();
    expect(screen.queryByText(/调试画像/)).not.toBeInTheDocument();
  });

  it("切换演示用户后保留调试画像面板", () => {
    state.selectedPersona.user_id = 7248;
    render(<RightRail />);
    expect(screen.getByText("调试画像 7248")).toBeInTheDocument();
    expect(screen.queryByText("正式画像面板")).not.toBeInTheDocument();
  });
});
