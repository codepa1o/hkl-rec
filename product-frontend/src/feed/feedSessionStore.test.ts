import { beforeEach, describe, expect, it } from "vitest";
import type { FeedItem } from "../api/types";
import {
  FEED_SESSION_SCHEMA_VERSION,
  FEED_SESSION_STORAGE_KEY,
  buildFeedContextKey,
  clearFeedSessionData,
  readFeedSnapshot,
  readPersonaSelection,
  saveFeedSnapshot,
  savePersonaSelection,
  type FeedSessionSnapshot,
} from "./feedSessionStore";

const item: FeedItem = {
  source_space: "mind",
  article_id: "N301",
  news_id: "N301",
  title: "First",
  abstract: "First article",
  url: "https://example.com/N301",
  source_domain: "example.com",
  category: "sports",
  subcategory: "football",
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

function snapshot(
  overrides: Partial<FeedSessionSnapshot> = {},
): FeedSessionSnapshot {
  const context = {
    sourceSpace: "mind" as const,
    personaUserId: 7248,
    category: "sports",
    language: "all" as const,
  };
  return {
    schemaVersion: FEED_SESSION_SCHEMA_VERSION,
    contextKey: buildFeedContextKey(context),
    sourceSpace: context.sourceSpace,
    personaUserId: context.personaUserId,
    category: context.category,
    language: context.language,
    pages: [{ requestId: "request-1", items: [item] }],
    feedUserId: context.personaUserId,
    nextCursor: "cursor-2",
    hasMore: true,
    anchorArticleId: "N301",
    anchorViewportTop: 180,
    scrollY: 2400,
    feedWatermark: null,
    savedAt: 1_000,
    lastAccessedAt: 1_000,
    ...overrides,
  };
}

describe("feedSessionStore", () => {
  beforeEach(() => sessionStorage.clear());

  it("isolates source, persona, category, and language in the context key", () => {
    const base = buildFeedContextKey({
      sourceSpace: "mind",
      personaUserId: 7248,
      category: "sports",
      language: "all",
    });

    expect(base).not.toBe(
      buildFeedContextKey({
        sourceSpace: "live",
        personaUserId: 7248,
        category: "sports",
        language: "all",
      }),
    );
    expect(base).not.toBe(
      buildFeedContextKey({
        sourceSpace: "mind",
        personaUserId: 1026,
        category: "sports",
        language: "all",
      }),
    );
    expect(base).not.toBe(
      buildFeedContextKey({
        sourceSpace: "mind",
        personaUserId: 7248,
        category: "finance",
        language: "all",
      }),
    );
    expect(base).not.toBe(
      buildFeedContextKey({
        sourceSpace: "mind",
        personaUserId: 7248,
        category: "sports",
        language: "zh",
      }),
    );
  });

  it("round-trips a valid feed snapshot", () => {
    const value = snapshot();

    expect(saveFeedSnapshot(value, { now: () => 1_000 })).toBe(true);
    expect(readFeedSnapshot(value.contextKey, { now: () => 1_100 })).toEqual({
      ...value,
      lastAccessedAt: 1_100,
    });
  });

  it("deletes corrupt and incompatible storage instead of throwing", () => {
    sessionStorage.setItem(FEED_SESSION_STORAGE_KEY, "not-json");
    expect(readFeedSnapshot("missing")).toBeNull();
    expect(sessionStorage.getItem(FEED_SESSION_STORAGE_KEY)).toBeNull();

    sessionStorage.setItem(
      FEED_SESSION_STORAGE_KEY,
      JSON.stringify({ schemaVersion: 999, sessions: {} }),
    );
    expect(readFeedSnapshot("missing")).toBeNull();
    expect(sessionStorage.getItem(FEED_SESSION_STORAGE_KEY)).toBeNull();
  });

  it("removes an incomplete snapshot while preserving valid contexts", () => {
    const valid = snapshot();
    sessionStorage.setItem(
      FEED_SESSION_STORAGE_KEY,
      JSON.stringify({
        schemaVersion: FEED_SESSION_SCHEMA_VERSION,
        sessions: {
          [valid.contextKey]: valid,
          incomplete: { schemaVersion: FEED_SESSION_SCHEMA_VERSION },
        },
      }),
    );

    expect(readFeedSnapshot("incomplete", { now: () => 1_100 })).toBeNull();
    const stored = JSON.parse(sessionStorage.getItem(FEED_SESSION_STORAGE_KEY) ?? "null");
    expect(stored.sessions).not.toHaveProperty("incomplete");
    expect(stored.sessions).toHaveProperty(valid.contextKey);
  });

  it("removes snapshots after the two-hour TTL", () => {
    const value = snapshot({ savedAt: 10_000, lastAccessedAt: 10_000 });
    saveFeedSnapshot(value, { now: () => 10_000 });

    expect(
      readFeedSnapshot(value.contextKey, {
        now: () => 10_000 + 2 * 60 * 60 * 1_000 + 1,
      }),
    ).toBeNull();
  });

  it("keeps only the eight most recently accessed contexts", () => {
    for (let index = 0; index < 9; index += 1) {
      const contextKey = buildFeedContextKey({
        sourceSpace: "mind",
        personaUserId: 7000 + index,
        category: null,
        language: "all",
      });
      saveFeedSnapshot(
        snapshot({
          contextKey,
          personaUserId: 7000 + index,
          feedUserId: 7000 + index,
          category: null,
          savedAt: index + 1,
          lastAccessedAt: index + 1,
        }),
        { now: () => index + 1 },
      );
    }

    const oldestKey = buildFeedContextKey({
      sourceSpace: "mind",
      personaUserId: 7000,
      category: null,
      language: "all",
    });
    const newestKey = buildFeedContextKey({
      sourceSpace: "mind",
      personaUserId: 7008,
      category: null,
      language: "all",
    });
    expect(readFeedSnapshot(oldestKey, { now: () => 20 })).toBeNull();
    expect(readFeedSnapshot(newestKey, { now: () => 20 })).not.toBeNull();
  });

  it("fails closed when session storage cannot be written", () => {
    const throwingStorage = {
      get length() {
        return 0;
      },
      clear() {},
      getItem() {
        return null;
      },
      key() {
        return null;
      },
      removeItem() {},
      setItem() {
        throw new DOMException("quota", "QuotaExceededError");
      },
    } satisfies Storage;

    expect(
      saveFeedSnapshot(snapshot(), {
        storage: throwingStorage,
        now: () => 1_000,
      }),
    ).toBe(false);
  });

  it("stores Persona choices by account and source and clears all session data", () => {
    savePersonaSelection(9, "mind", 7248);
    savePersonaSelection(9, "live", 1026);
    savePersonaSelection(10, "mind", 7004);
    saveFeedSnapshot(snapshot(), { now: () => 1_000 });

    expect(readPersonaSelection(9, "mind")).toBe(7248);
    expect(readPersonaSelection(9, "live")).toBe(1026);
    expect(readPersonaSelection(10, "mind")).toBe(7004);

    clearFeedSessionData();

    expect(readPersonaSelection(9, "mind")).toBeNull();
    expect(readPersonaSelection(9, "live")).toBeNull();
    expect(sessionStorage.getItem(FEED_SESSION_STORAGE_KEY)).toBeNull();
  });
});
