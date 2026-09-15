import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  FEED_SESSION_SCHEMA_VERSION,
  buildFeedContextKey,
  readFeedSnapshot,
  removeFeedSnapshot,
  saveFeedSnapshot,
  type FeedContextIdentity,
  type FeedPageSnapshot,
  type FeedSessionSnapshot,
} from "./feedSessionStore";

export type FeedHydrationStatus = "pending" | "restored" | "miss";

interface FeedRestorationState {
  loadedContextKey: string | null;
  pages: FeedPageSnapshot[];
  feedUserId: number | null;
  nextCursor: string | null;
  hasMore: boolean;
  feedWatermark: string | null;
}

interface FeedRestorationOptions {
  context: FeedContextIdentity | null;
  state: FeedRestorationState;
  renderedArticleIds: string[];
  onHydrate: (snapshot: FeedSessionSnapshot) => void;
}

interface FeedRestorationController {
  contextKey: string | null;
  hydrationStatus: FeedHydrationStatus;
  captureArticle: (articleId: string) => void;
  persist: () => boolean;
  clear: () => void;
}

function snapshotMatchesContext(
  snapshot: FeedSessionSnapshot,
  context: FeedContextIdentity,
): boolean {
  return (
    snapshot.sourceSpace === context.sourceSpace &&
    snapshot.personaUserId === context.personaUserId &&
    snapshot.feedUserId === context.personaUserId &&
    snapshot.category === context.category &&
    snapshot.language === context.language
  );
}

export function useFeedSessionRestoration({
  context,
  state,
  renderedArticleIds,
  onHydrate,
}: FeedRestorationOptions): FeedRestorationController {
  const contextKey = useMemo(
    () => (context ? buildFeedContextKey(context) : null),
    [context?.sourceSpace, context?.personaUserId, context?.category, context?.language],
  );
  const [hydrationState, setHydrationState] = useState<{
    contextKey: string | null;
    status: FeedHydrationStatus;
  }>({ contextKey: null, status: "pending" });
  const hydrationStatus =
    hydrationState.contextKey === contextKey ? hydrationState.status : "pending";
  const stateRef = useRef(state);
  const contextRef = useRef(context);
  const onHydrateRef = useRef(onHydrate);
  const snapshotRef = useRef<FeedSessionSnapshot | null>(null);
  const anchorArticleIdRef = useRef<string | null>(null);
  const anchorViewportTopRef = useRef<number | null>(null);
  const restoredTokenRef = useRef<string | null>(null);

  stateRef.current = state;
  contextRef.current = context;
  onHydrateRef.current = onHydrate;

  useEffect(() => {
    restoredTokenRef.current = null;
    anchorArticleIdRef.current = null;
    anchorViewportTopRef.current = null;
    snapshotRef.current = null;
    if (!contextKey || !contextRef.current) {
      setHydrationState({ contextKey, status: "pending" });
      return;
    }
    const snapshot = readFeedSnapshot(contextKey);
    if (snapshot && snapshotMatchesContext(snapshot, contextRef.current)) {
      snapshotRef.current = snapshot;
      anchorArticleIdRef.current = snapshot.anchorArticleId;
      anchorViewportTopRef.current = snapshot.anchorViewportTop;
      onHydrateRef.current(snapshot);
      setHydrationState({ contextKey, status: "restored" });
      return;
    }
    setHydrationState({ contextKey, status: "miss" });
  }, [contextKey]);

  const persist = useCallback((): boolean => {
    const activeContext = contextRef.current;
    const currentState = stateRef.current;
    if (
      !contextKey ||
      !activeContext ||
      currentState.loadedContextKey !== contextKey ||
      currentState.feedUserId !== activeContext.personaUserId ||
      currentState.pages.length === 0
    ) {
      return false;
    }
    const now = Date.now();
    const next: FeedSessionSnapshot = {
      schemaVersion: FEED_SESSION_SCHEMA_VERSION,
      contextKey,
      sourceSpace: activeContext.sourceSpace,
      personaUserId: activeContext.personaUserId,
      category: activeContext.category,
      language: activeContext.language,
      pages: currentState.pages,
      feedUserId: currentState.feedUserId,
      nextCursor: currentState.nextCursor,
      hasMore: currentState.hasMore,
      anchorArticleId: anchorArticleIdRef.current,
      anchorViewportTop: anchorViewportTopRef.current,
      scrollY: window.scrollY,
      feedWatermark: currentState.feedWatermark,
      savedAt: now,
      lastAccessedAt: now,
    };
    const saved = saveFeedSnapshot(next);
    if (saved) snapshotRef.current = next;
    return saved;
  }, [contextKey]);

  const captureArticle = useCallback(
    (articleId: string) => {
      anchorArticleIdRef.current = articleId;
      const anchor = document.querySelector<HTMLElement>(
        `[data-article-id="${articleId}"]`,
      );
      anchorViewportTopRef.current = anchor?.getBoundingClientRect().top ?? null;
      persist();
    },
    [persist],
  );

  const clear = useCallback(() => {
    if (contextKey) removeFeedSnapshot(contextKey);
    snapshotRef.current = null;
    anchorArticleIdRef.current = null;
    anchorViewportTopRef.current = null;
    restoredTokenRef.current = null;
    setHydrationState({ contextKey, status: "miss" });
  }, [contextKey]);

  useEffect(() => {
    if (hydrationStatus === "pending") return;
    persist();
  }, [
    hydrationStatus,
    state.pages,
    state.loadedContextKey,
    state.feedUserId,
    state.nextCursor,
    state.hasMore,
    state.feedWatermark,
    persist,
  ]);

  useEffect(() => {
    const handlePageHide = () => {
      persist();
    };
    window.addEventListener("pagehide", handlePageHide);
    return () => window.removeEventListener("pagehide", handlePageHide);
  }, [persist]);

  const renderedKey = renderedArticleIds.join("\u0000");
  useEffect(() => {
    const snapshot = snapshotRef.current;
    if (hydrationStatus !== "restored" || !snapshot || renderedKey.length === 0) return;
    const restoreToken = `${snapshot.contextKey}:${snapshot.savedAt}`;
    if (restoredTokenRef.current === restoreToken) return;
    const frame = window.requestAnimationFrame(() => {
      const anchor = snapshot.anchorArticleId
        ? document.querySelector<HTMLElement>(
            `[data-article-id="${snapshot.anchorArticleId}"]`,
          )
        : null;
      if (anchor && snapshot.anchorViewportTop !== null) {
        window.scrollBy({
          top: anchor.getBoundingClientRect().top - snapshot.anchorViewportTop,
          left: 0,
          behavior: "auto",
        });
      } else {
        window.scrollTo({ top: snapshot.scrollY, left: 0, behavior: "auto" });
      }
      restoredTokenRef.current = restoreToken;
    });
    return () => window.cancelAnimationFrame(frame);
  }, [hydrationStatus, renderedKey]);

  return { contextKey, hydrationStatus, captureArticle, persist, clear };
}
