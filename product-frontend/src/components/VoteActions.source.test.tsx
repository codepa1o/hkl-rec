import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { trackEvent } from "../api/client";
import VoteActions from "./VoteActions";

vi.mock("../api/client", () => ({
  trackEvent: vi.fn().mockResolvedValue(undefined),
}));

describe("VoteActions source identity", () => {
  it("使用来源和规范文章编号上报投票", async () => {
    render(
      <VoteActions
        sourceSpace="live"
        articleId="L0123456789abcdef0123456789abcdef"
        userId={7004}
        requestId="req-live"
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "赞同" }));

    await waitFor(() =>
      expect(trackEvent).toHaveBeenCalledWith({
        user_id: 7004,
        source_space: "live",
        event_type: "upvote",
        surface: "feed",
        article_id: "L0123456789abcdef0123456789abcdef",
        request_id: "req-live",
      }),
    );
  });
});
