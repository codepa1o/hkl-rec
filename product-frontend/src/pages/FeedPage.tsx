import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  ApiError,
  getFeed,
  getFeedUpdateStatus,
  newClientId,
  stableClientId,
  trackEvent,
} from "../api/client";
import type { FeedItem, LiveLanguage } from "../api/types";
import PostCard from "../components/PostCard";
import { usePersona } from "../context/PersonaContext";
import { useSourceSpace } from "../context/SourceSpaceContext";
import { localizeCategoryName, localizeInterfaceError } from "../localization";
import type { FeedSessionSnapshot } from "../feed/feedSessionStore";
import { useFeedSessionRestoration } from "../feed/useFeedSessionRestoration";

const PAGE_SIZE = 20;

interface FeedPageBatch {
  requestId: string;
  items: FeedItem[];
}

interface FeedEntry {
  item: FeedItem;
  requestId: string;
}

function latestFeedWatermark(items: FeedItem[]): string | null {
  const timestamps = items
    .map((item) => item.discovered_at)
    .filter((value): value is string => Boolean(value));
  return timestamps.length > 0 ? timestamps.sort().at(-1) ?? null : null;
}

export default function FeedPage() {
  const { selectedPersona, bumpProfile } = usePersona();
  const { sourceSpace } = useSourceSpace();
  const location = useLocation();
  const navigate = useNavigate();
  const searchParams = useMemo(() => new URLSearchParams(location.search), [location.search]);
  const routeCategory = searchParams.get("category") || undefined;
  const category = sourceSpace === "mind" ? routeCategory : undefined;
  const routeLanguage = searchParams.get("language");
  const language: LiveLanguage =
    sourceSpace === "live" && (routeLanguage === "zh" || routeLanguage === "en")
      ? routeLanguage
      : "all";
  const [pages, setPages] = useState<FeedPageBatch[]>([]);
  const [feedUserId, setFeedUserId] = useState<number | null>(null);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [invalidCategory, setInvalidCategory] = useState(false);
  const [loadMoreError, setLoadMoreError] = useState<string | null>(null);
  const [trackingError, setTrackingError] = useState<string | null>(null);
  const [feedWatermark, setFeedWatermark] = useState<string | null>(null);
  const [hasNewUpdates, setHasNewUpdates] = useState(false);
  const trackedRef = useRef<Set<string>>(new Set());
  const loadingMoreRef = useRef(false);
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  const activeSessionRef = useRef("");
  const loadRequestId = useMemo(
    () =>
      stableClientId(
        "feed",
        `${sourceSpace}:${selectedPersona?.user_id ?? "none"}:${category ?? "all"}:${language}`,
      ),
    [category, language, selectedPersona?.user_id, sourceSpace],
  );

  useEffect(() => {
    if (sourceSpace !== "live" || !routeCategory) return;
    const next = new URLSearchParams(location.search);
    next.delete("category");
    const query = next.toString();
    navigate({ pathname: "/", search: query ? `?${query}` : "" }, { replace: true });
  }, [location.search, navigate, routeCategory, sourceSpace]);

  const context = useMemo(
    () =>
      selectedPersona
        ? {
            sourceSpace,
            personaUserId: selectedPersona.user_id,
            category: category ?? null,
            language,
          }
        : null,
    [category, language, selectedPersona?.user_id, sourceSpace],
  );
  const renderedArticleIds = useMemo(
    () => pages.flatMap((page) => page.items.map((item) => item.article_id)),
    [pages],
  );
  const hydrateFeed = useCallback(
    (snapshot: FeedSessionSnapshot) => {
      activeSessionRef.current = snapshot.contextKey;
      loadingMoreRef.current = false;
      trackedRef.current = new Set(
        snapshot.pages.flatMap((page) =>
          page.items.map(
            (item) =>
              `${snapshot.sourceSpace}:${snapshot.personaUserId}:${page.requestId}:${item.article_id}`,
          ),
        ),
      );
      setPages(snapshot.pages);
      setFeedUserId(snapshot.feedUserId);
      setNextCursor(snapshot.nextCursor);
      setHasMore(snapshot.hasMore);
      setFeedWatermark(snapshot.feedWatermark);
      setLoading(false);
      setLoadingMore(false);
      setError(null);
      setInvalidCategory(false);
      setLoadMoreError(null);
    },
    [],
  );
  const restoration = useFeedSessionRestoration({
    context,
    state: { pages, feedUserId, nextCursor, hasMore, feedWatermark },
    renderedArticleIds,
    onHydrate: hydrateFeed,
  });

  useEffect(() => {
    setHasNewUpdates(false);
    if (
      restoration.hydrationStatus !== "restored" ||
      sourceSpace !== "live" ||
      !selectedPersona ||
      !feedWatermark
    ) {
      return;
    }
    let cancelled = false;
    const checkForUpdates = async () => {
      if (document.visibilityState === "hidden") return;
      try {
        const response = await getFeedUpdateStatus(
          selectedPersona.user_id,
          sourceSpace,
          language,
          feedWatermark,
        );
        if (!cancelled && response.source_space === sourceSpace) {
          setHasNewUpdates(response.has_updates);
        }
      } catch {
        // A background freshness check must never replace the restored feed.
      }
    };
    void checkForUpdates();
    const interval = window.setInterval(() => void checkForUpdates(), 60_000);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [
    feedWatermark,
    language,
    restoration.contextKey,
    restoration.hydrationStatus,
    selectedPersona?.user_id,
    sourceSpace,
  ]);

  const reloadLatestFeed = useCallback(() => {
    restoration.clear();
    setHasNewUpdates(false);
    loadingMoreRef.current = false;
    setPages([]);
    setFeedUserId(null);
    setNextCursor(null);
    setHasMore(false);
    setFeedWatermark(null);
    setLoading(false);
    setLoadingMore(false);
    setError(null);
    setInvalidCategory(false);
    setLoadMoreError(null);
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
  }, [restoration.clear]);

  useEffect(() => {
    if (!selectedPersona || restoration.hydrationStatus !== "miss") return;
    let cancelled = false;
    activeSessionRef.current = loadRequestId;
    loadingMoreRef.current = false;
    setLoading(true);
    setLoadingMore(false);
    setError(null);
    setInvalidCategory(false);
    setLoadMoreError(null);
    setPages([]);
    setNextCursor(null);
    setHasMore(false);
    setFeedUserId(null);
    setFeedWatermark(null);
    trackedRef.current = new Set();
    getFeed(
      selectedPersona.user_id,
      PAGE_SIZE,
      true,
      loadRequestId,
      undefined,
      category,
      sourceSpace,
      language,
    )
      .then((res) => {
        if (cancelled || res.source_space !== sourceSpace) return;
        setPages([{ requestId: res.request_id, items: res.items }]);
        setNextCursor(res.next_cursor);
        setHasMore(res.has_more);
        setFeedUserId(res.user_id);
        setFeedWatermark(latestFeedWatermark(res.items));
      })
      .catch((err: Error) => {
        if (cancelled) return;
        setInvalidCategory(err instanceof ApiError && err.status === 422);
        setError(err.message);
      })
      .finally(() => {
        if (cancelled) return;
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [
    selectedPersona,
    restoration.hydrationStatus,
    loadRequestId,
    category,
    sourceSpace,
    language,
  ]);

  const visibleEntries = useMemo<FeedEntry[]>(() => {
    if (!selectedPersona || feedUserId !== selectedPersona.user_id) return [];
    const unique = new Map<string, FeedEntry>();
    pages.forEach((page) => {
      page.items.forEach((item) => {
        if (!unique.has(item.article_id)) {
          unique.set(item.article_id, { item, requestId: page.requestId });
        }
      });
    });
    return [...unique.values()];
  }, [pages, selectedPersona, feedUserId]);

  useEffect(() => {
    if (!selectedPersona || visibleEntries.length === 0) return;
    const pending = visibleEntries
      .map((entry) => ({
        entry,
        key: `${sourceSpace}:${selectedPersona.user_id}:${entry.requestId}:${entry.item.article_id}`,
      }))
      .filter(({ key }) => !trackedRef.current.has(key));
    if (pending.length === 0) return;

    pending.forEach(({ key }) => trackedRef.current.add(key));
    setTrackingError(null);
    void Promise.allSettled(
      pending.map(({ entry, key }) =>
        trackEvent({
          event_id: `imp-${key}`,
          user_id: selectedPersona.user_id,
          source_space: sourceSpace,
          event_type: "feed_impression",
          surface: "feed",
          article_id: entry.item.article_id,
          request_id: entry.requestId,
          sponsored_delivery_id: entry.item.sponsored?.delivery_id ?? null,
        }),
      ),
    ).then((results) => {
      const failedKeys: string[] = [];
      results.forEach((result, index) => {
        if (result.status === "rejected") {
          failedKeys.push(pending[index].key);
          trackedRef.current.delete(pending[index].key);
        }
      });
      if (failedKeys.length > 0) {
        setTrackingError(`${failedKeys.length} 篇内容的曝光记录失败，请稍后重试。`);
      }
    });
  }, [selectedPersona, sourceSpace, visibleEntries]);

  const loadMore = useCallback(async () => {
    if (
      !selectedPersona ||
      feedUserId !== selectedPersona.user_id ||
      !nextCursor ||
      !hasMore ||
      loadingMoreRef.current
    ) {
      return;
    }
    const sessionId = activeSessionRef.current;
    const userId = selectedPersona.user_id;
    const pageRequestId = newClientId("feed-page");
    loadingMoreRef.current = true;
    setLoadingMore(true);
    setLoadMoreError(null);
    try {
      const res = await getFeed(
        userId,
        PAGE_SIZE,
        true,
        pageRequestId,
        nextCursor,
        category,
        sourceSpace,
        language,
      );
      if (activeSessionRef.current !== sessionId || res.source_space !== sourceSpace) return;
      setPages((current) => [
        ...current,
        { requestId: res.request_id, items: res.items },
      ]);
      setNextCursor(res.next_cursor);
      setHasMore(res.has_more);
      setFeedWatermark((current) => latestFeedWatermark(res.items) ?? current);
    } catch (err) {
      if (activeSessionRef.current !== sessionId) return;
      const message = err instanceof Error ? err.message : "未知错误";
      setLoadMoreError(`加载更多新闻失败：${localizeInterfaceError(message)}`);
    } finally {
      if (activeSessionRef.current === sessionId) {
        loadingMoreRef.current = false;
        setLoadingMore(false);
      }
    }
  }, [selectedPersona, feedUserId, nextCursor, hasMore, category, sourceSpace, language]);

  useEffect(() => {
    const sentinel = sentinelRef.current;
    if (!sentinel || !hasMore || !nextCursor || loadingMore || loadMoreError) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) void loadMore();
      },
      { rootMargin: "800px 0px" },
    );
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [hasMore, nextCursor, loadingMore, loadMoreError, loadMore]);

  const handleClick = useCallback(
    (entry: FeedEntry) => {
      if (!selectedPersona) return;
      const articleId = entry.item.article_id;
      void trackEvent({
        event_id: `click-${sourceSpace}:${selectedPersona.user_id}:${entry.requestId}:${articleId}`,
        user_id: selectedPersona.user_id,
        source_space: sourceSpace,
        event_type: "recommendation_click",
        surface: "feed",
        article_id: articleId,
        request_id: entry.requestId,
        sponsored_delivery_id: entry.item.sponsored?.delivery_id ?? null,
      })
        .then(() => {
          setTrackingError(null);
          bumpProfile();
        })
        .catch((err: Error) =>
          setTrackingError(`点击记录失败：${localizeInterfaceError(err.message)}`),
        );
    },
    [selectedPersona, sourceSpace, bumpProfile],
  );

  if (!selectedPersona) {
    return <div className="zr-status">请选择一个用户画像以查看推荐信息流。</div>;
  }
  if (error) {
    if (invalidCategory) {
      return (
        <div className="zr-status">
          该新闻分类不存在或已不可用。<Link to="/">查看全部新闻</Link>
        </div>
      );
    }
    return <div className="zr-status">信息流加载失败：{localizeInterfaceError(error)}</div>;
  }

  const categoryLabel = category ? localizeCategoryName(category) : null;

  return (
    <main className="zr-center">
      <header className="zr-page-header">
        <span className="zr-eyebrow">
          {sourceSpace === "live" ? "持续更新的双语资讯" : "你的每日阅读"}
        </span>
        <h1>
          {sourceSpace === "live"
            ? "实时新闻"
            : categoryLabel
              ? `${categoryLabel}新闻`
              : "为你推荐"}
        </h1>
        <p>
          {sourceSpace === "live"
            ? "按新鲜度与来源多样性持续更新"
            : categoryLabel
              ? `在${categoryLabel}分类内，根据你的阅读兴趣持续推荐`
              : "根据你的阅读兴趣持续更新"}
        </p>
      </header>

      {sourceSpace === "live" && (
        <div className="zr-language-filter" aria-label="实时新闻语言">
          {(["all", "zh", "en"] as const).map((value) => (
            <button
              type="button"
              key={value}
              aria-pressed={language === value}
              onClick={() => {
                const next = new URLSearchParams(location.search);
                next.delete("category");
                if (value === "all") next.delete("language");
                else next.set("language", value);
                const query = next.toString();
                navigate(
                  { pathname: "/", search: query ? `?${query}` : "" },
                  { replace: true },
                );
              }}
            >
              {value === "all" ? "全部" : value === "zh" ? "中文" : "English"}
            </button>
          ))}
        </div>
      )}

      {loading && visibleEntries.length === 0 && (
        <div className="zr-status">正在加载信息流…</div>
      )}
      {trackingError && <div className="zr-status">{trackingError}</div>}

      {hasNewUpdates && (
        <button
          type="button"
          className="zr-feed-update-prompt"
          onClick={reloadLatestFeed}
        >
          有新新闻
        </button>
      )}

      {!loading && visibleEntries.length === 0 && (
        <div className="zr-status">
          {categoryLabel
            ? `当前${categoryLabel}分类暂无文章，请尝试其他新闻分类。`
            : "当前信息流暂无文章，请尝试选择其他用户画像。"}
        </div>
      )}

      {visibleEntries.length > 0 && (
        <div className="zr-feed-count">已加载 {visibleEntries.length} 篇新闻</div>
      )}

      {visibleEntries.map((entry) => (
        <PostCard
          key={entry.item.article_id}
          item={entry.item}
          userId={selectedPersona.user_id}
          requestId={entry.requestId}
          showReason
          onTrackClick={() => handleClick(entry)}
          onProfileChanged={bumpProfile}
          feedNavigationState={
            restoration.contextKey
              ? { fromFeed: true, feedContextKey: restoration.contextKey }
              : undefined
          }
          onOpenArticle={restoration.captureArticle}
        />
      ))}

      <div ref={sentinelRef} className="zr-feed-sentinel" data-testid="feed-sentinel" />
      {loadingMore && <div className="zr-status">正在加载更多新闻…</div>}
      {loadMoreError && (
        <div className="zr-feed-retry" role="alert">
          <span>{loadMoreError}</span>
          <button type="button" onClick={() => void loadMore()}>
            重新加载
          </button>
        </div>
      )}
      {!loading && visibleEntries.length > 0 && !hasMore && (
        <div className="zr-feed-end">已经看完本轮信息流</div>
      )}
    </main>
  );
}
