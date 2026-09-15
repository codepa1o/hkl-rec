import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { FeedItem } from "../api/types";
import {
  FEED_SESSION_SCHEMA_VERSION,
  buildFeedContextKey,
  readFeedSnapshot,
  saveFeedSnapshot,
  type FeedContextIdentity,
  type FeedSessionSnapshot,
} from "./feedSessionStore";
import { useFeedSessionRestoration } from "./useFeedSessionRestoration";

const context: FeedContextIdentity = {
  sourceSpace: "mind",
  personaUserId: 7248,
  category: null,
  language: "all",
};

const item: FeedItem = {
  source_space: "mind",
  article_id: "N343",
  news_id: "N343",
  title: "Forty-third",
  abstract: "Article",
  url: "https://example.com/N343",
  source_domain: "example.com",
  category: "news",
  subcategory: "world",
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
  content_type: "organic",
};

function storedSnapshot(): FeedSessionSnapshot {
  return {
    schemaVersion: FEED_SESSION_SCHEMA_VERSION,
    contextKey: buildFeedContextKey(context),
    sourceSpace: "mind",
    personaUserId: 7248,
    category: null,
    language: "all",
    pages: [{ requestId: "request-3", items: [item] }],
    feedUserId: 7248,
    nextCursor: "cursor-4",
    hasMore: true,
    anchorArticleId: "N343",
    anchorViewportTop: 140,
    scrollY: 4100,
    feedWatermark: null,
    savedAt: Date.now(),
    lastAccessedAt: Date.now(),
  };
}

const currentState = {
  loadedContextKey: buildFeedContextKey(context),
  pages: [{ requestId: "request-3", items: [item] }],
  feedUserId: 7248,
  nextCursor: "cursor-4",
  hasMore: true,
  feedWatermark: null,
};

describe("useFeedSessionRestoration", () => {
  beforeEach(() => {
    sessionStorage.clear();
    document.body.innerHTML = "";
    vi.restoreAllMocks();
    vi.spyOn(window, "requestAnimationFrame").mockImplementation((callback) => {
      callback(0);
      return 1;
    });
    vi.spyOn(window, "cancelAnimationFrame").mockImplementation(() => undefined);
    vi.spyOn(window, "scrollBy").mockImplementation(() => undefined);
    vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);
    Object.defineProperty(window, "scrollY", { configurable: true, value: 4100 });
  });

  it("hydrates a matching snapshot before allowing a new load", async () => {
    const value = storedSnapshot();
    saveFeedSnapshot(value);
    const onHydrate = vi.fn();

    const { result } = renderHook(() =>
      useFeedSessionRestoration({
        context,
        state: currentState,
        renderedArticleIds: [],
        onHydrate,
      }),
    );

    await waitFor(() => expect(result.current.hydrationStatus).toBe("restored"));
    expect(onHydrate).toHaveBeenCalledWith(
      expect.objectContaining({ contextKey: value.contextKey, nextCursor: "cursor-4" }),
    );
  });

  it("reports a miss when no matching snapshot exists", async () => {
    const { result } = renderHook(() =>
      useFeedSessionRestoration({
        context,
        state: currentState,
        renderedArticleIds: [],
        onHydrate: vi.fn(),
      }),
    );

    await waitFor(() => expect(result.current.hydrationStatus).toBe("miss"));
  });

  it("captures the clicked card viewport offset before navigation", async () => {
    const anchor = document.createElement("article");
    anchor.dataset.articleId = "N343";
    anchor.getBoundingClientRect = vi.fn(
      () => ({ top: 175 }) as DOMRect,
    );
    document.body.append(anchor);
    const { result } = renderHook(() =>
      useFeedSessionRestoration({
        context,
        state: currentState,
        renderedArticleIds: ["N343"],
        onHydrate: vi.fn(),
      }),
    );
    await waitFor(() => expect(result.current.hydrationStatus).toBe("miss"));

    act(() => result.current.captureArticle("N343"));

    expect(readFeedSnapshot(result.current.contextKey!)).toEqual(
      expect.objectContaining({
        anchorArticleId: "N343",
        anchorViewportTop: 175,
        scrollY: 4100,
      }),
    );
  });

  it("restores the anchor offset once when the article is rendered", async () => {
    saveFeedSnapshot(storedSnapshot());
    const anchor = document.createElement("article");
    anchor.dataset.articleId = "N343";
    anchor.getBoundingClientRect = vi.fn(
      () => ({ top: 260 }) as DOMRect,
    );
    document.body.append(anchor);

    const { rerender } = renderHook(
      ({ renderedArticleIds }) =>
        useFeedSessionRestoration({
          context,
          state: currentState,
          renderedArticleIds,
          onHydrate: vi.fn(),
        }),
      { initialProps: { renderedArticleIds: ["N343"] } },
    );

    await waitFor(() =>
      expect(window.scrollBy).toHaveBeenCalledWith({
        top: 120,
        left: 0,
        behavior: "auto",
      }),
    );
    rerender({ renderedArticleIds: ["N343"] });
    expect(window.scrollBy).toHaveBeenCalledTimes(1);
  });

  it("falls back to absolute scroll when the anchor is missing", async () => {
    saveFeedSnapshot(storedSnapshot());

    renderHook(() =>
      useFeedSessionRestoration({
        context,
        state: currentState,
        renderedArticleIds: ["N343"],
        onHydrate: vi.fn(),
      }),
    );

    await waitFor(() =>
      expect(window.scrollTo).toHaveBeenCalledWith({
        top: 4100,
        left: 0,
        behavior: "auto",
      }),
    );
  });

  it("persists the latest state on pagehide", async () => {
    const { result, rerender } = renderHook(
      ({ nextCursor }) =>
        useFeedSessionRestoration({
          context,
          state: { ...currentState, nextCursor },
          renderedArticleIds: ["N343"],
          onHydrate: vi.fn(),
        }),
      { initialProps: { nextCursor: "cursor-4" as string | null } },
    );
    await waitFor(() => expect(result.current.hydrationStatus).toBe("miss"));
    rerender({ nextCursor: "cursor-5" });

    act(() => window.dispatchEvent(new Event("pagehide")));

    expect(readFeedSnapshot(result.current.contextKey!)).toEqual(
      expect.objectContaining({ nextCursor: "cursor-5" }),
    );
  });
});
