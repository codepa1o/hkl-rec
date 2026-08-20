import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { trackEvent } from "../api/client";
import VoteActions from "./VoteActions";

vi.mock("../api/client", () => ({
  trackEvent: vi.fn().mockResolvedValue(undefined),
}));

describe("VoteActions", () => {
  beforeEach(() => {
    vi.mocked(trackEvent).mockClear();
  });

  it("使用与界面一致的单色线框拇指图标，同时保留按钮说明", () => {
    render(
      <VoteActions
        sourceSpace="mind"
        articleId="N1001"
        userId={7004}
        requestId="req-1"
      />,
    );

    const upvoteButton = screen.getByRole("button", { name: "赞同" });
    const downvoteButton = screen.getByRole("button", { name: "不赞同" });
    expect(upvoteButton.querySelector(".lucide-thumbs-up")).toHaveAttribute(
      "aria-hidden",
      "true",
    );
    expect(downvoteButton.querySelector(".lucide-thumbs-down")).toHaveAttribute(
      "aria-hidden",
      "true",
    );
    expect(upvoteButton).not.toHaveTextContent("👍");
    expect(downvoteButton).not.toHaveTextContent("👎");
  });

  it("点击拇指按钮后仍上报原有投票事件和选中状态", async () => {
    render(
      <VoteActions
        sourceSpace="mind"
        articleId="N1001"
        userId={7004}
        requestId="req-1"
      />,
    );

    const upvoteButton = screen.getByRole("button", { name: "赞同" });
    fireEvent.click(upvoteButton);

    expect(upvoteButton).toHaveAttribute("aria-pressed", "true");
    await waitFor(() =>
      expect(trackEvent).toHaveBeenCalledWith({
        user_id: 7004,
        source_space: "mind",
        event_type: "upvote",
        surface: "feed",
        article_id: "N1001",
        request_id: "req-1",
      }),
    );
  });
});
