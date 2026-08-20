import { StrictMode } from "react";
import { render, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import SearchPage from "./SearchPage";
import { postSearch } from "../api/client";
import type { NewsSpace, SearchResponse } from "../api/types";

const bumpProfile = vi.fn();
const selectedPersona = {
  user_id: 7248,
  display_name: "Backend Explorer",
  behavior_score: 0,
  top_topics: [],
};
const sourceState: { sourceSpace: NewsSpace } = { sourceSpace: "mind" };

vi.mock("../context/SourceSpaceContext", () => ({
  useSourceSpace: () => sourceState,
}));

vi.mock("../context/PersonaContext", () => ({
  usePersona: () => ({
    selectedPersona,
    bumpProfile,
  }),
}));

vi.mock("react-router-dom", async (importOriginal) => {
  const actual = await importOriginal<typeof import("react-router-dom")>();
  return {
    ...actual,
    useLocation: () => ({ key: "search-route" }),
    useSearchParams: () => [new URLSearchParams("q=backend")],
  };
});

vi.mock("../api/client", () => ({
  postSearch: vi.fn(),
  stableClientId: vi.fn(() => "search-event-stable"),
  trackEvent: vi.fn(),
}));

vi.mock("../components/PostCard", () => ({
  default: () => <div>post</div>,
}));

vi.mock("../components/SearchBox", () => ({
  default: () => <div>search box</div>,
}));

describe("SearchPage idempotency", () => {
  beforeEach(() => {
    sourceState.sourceSpace = "mind";
    vi.clearAllMocks();
    vi.mocked(postSearch).mockResolvedValue({
      source_space: "mind",
      user_id: 7248,
      request_id: "search-event-stable",
      query_key: "10 11",
      items: [],
    });
  });

  it("reuses one event ID across StrictMode effect retries", async () => {
    render(
      <StrictMode>
        <SearchPage />
      </StrictMode>,
    );

    await waitFor(() => expect(postSearch).toHaveBeenCalled());
    expect(
      new Set(vi.mocked(postSearch).mock.calls.map((call) => call[3])),
    ).toEqual(new Set(["search-event-stable"]));
    expect(new Set(vi.mocked(postSearch).mock.calls.map((call) => call[4]))).toEqual(
      new Set(["mind"]),
    );
  });

  it("切换到实时新闻后忽略迟到的 MIND 搜索响应", async () => {
    let resolveMind!: (response: SearchResponse) => void;
    const mindResponse = new Promise<SearchResponse>((resolve) => {
      resolveMind = resolve;
    });
    vi.mocked(postSearch).mockImplementation((_userId, _input, _size, _eventId, space) =>
      space === "mind"
        ? mindResponse
        : Promise.resolve({
            source_space: "live",
            user_id: 7248,
            request_id: "live-request",
            query_key: "backend",
            items: [],
          }),
    );

    const view = render(<SearchPage />);
    sourceState.sourceSpace = "live";
    view.rerender(<SearchPage />);
    await waitFor(() =>
      expect(postSearch).toHaveBeenCalledWith(
        7248,
        { queryText: "backend" },
        10,
        "search-event-stable",
        "live",
      ),
    );
    resolveMind({
      source_space: "mind",
      user_id: 7248,
      request_id: "mind-request",
      query_key: "backend",
      items: [],
    });
    await Promise.resolve();
    expect(bumpProfile).toHaveBeenCalledTimes(1);
  });
});
