import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { ApiError, getFeed, newClientId, stableClientId, trackEvent } from "../api/client";
import type { FeedItem } from "../api/types";
import PostCard from "../components/PostCard";
import { usePersona } from "../context/PersonaContext";
import { localizeCategoryName, localizeInterfaceError } from "../localization";

const PAGE_SIZE = 20;

interface FeedPageBatch {
  requestId: string;
  items: FeedItem[];
}

interface FeedEntry {
  item: FeedItem;
  requestId: string;
}

export default function FeedPage() {
  const { selectedPersona, refreshTick, bumpProfile } = usePersona();
  const location = useLocation();
  const category = useMemo(
    () => new URLSearchParams(location.search).get("category") || undefined,
    [location.search],
  );
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
  const trackedRef = useRef<Set<string>>(new Set());
  const loadingMoreRef = useRef(false);
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  const activeSessionRef = useRef("");
  const loadRequestId = useMemo(
    () =>
      stableClientId(
        "feed",
        `${location.key}:${selectedPersona?.user_id ?? "none"}:${refreshTick}:${category ?? "all"}`,
      ),
    [category, location.key, selectedPersona?.user_id, refreshTick],
  );

  useEffect(() => {
    if (!selectedPersona) return;
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
    trackedRef.current = new Set();
    getFeed(selectedPersona.user_id, PAGE_SIZE, true, loadRequestId, undefined, category)
      .then((res) => {
        if (cancelled) return;
        setPages([{ requestId: res.request_id, items: res.items }]);
        setNextCursor(res.next_cursor);
        setHasMore(res.has_more);
        setFeedUserId(res.user_id);
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
  }, [selectedPersona, refreshTick, loadRequestId, category]);

  const visibleEntries = useMemo<FeedEntry[]>(() => {
    if (!selectedPersona || feedUserId !== selectedPersona.user_id) return [];
    const unique = new Map<string, FeedEntry>();
    pages.forEach((page) => {
      page.items.forEach((item) => {
        if (!unique.has(item.news_id)) {
          unique.set(item.news_id, { item, requestId: page.requestId });
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
        key: `${selectedPersona.user_id}:${entry.requestId}:${entry.item.news_id}`,
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
          event_type: "feed_impression",
          surface: "feed",
          news_id: entry.item.news_id,
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
  }, [selectedPersona, visibleEntries]);

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
      );
      if (activeSessionRef.current !== sessionId) return;
      setPages((current) => [
        ...current,
        { requestId: res.request_id, items: res.items },
      ]);
      setNextCursor(res.next_cursor);
      setHasMore(res.has_more);
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
  }, [selectedPersona, feedUserId, nextCursor, hasMore, category]);

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
      const newsId = entry.item.news_id;
      void trackEvent({
        event_id: `click-${selectedPersona.user_id}:${entry.requestId}:${newsId}`,
        user_id: selectedPersona.user_id,
        event_type: "recommendation_click",
        surface: "feed",
        news_id: newsId,
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
    [selectedPersona, bumpProfile],
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
        <span className="zr-eyebrow">你的每日阅读</span>
        <h1>{categoryLabel ? `${categoryLabel}新闻` : "为你推荐"}</h1>
        <p>
          {categoryLabel
            ? `在${categoryLabel}分类内，根据你的阅读兴趣持续推荐`
            : "根据你的阅读兴趣持续更新"}
        </p>
      </header>

      {loading && visibleEntries.length === 0 && (
        <div className="zr-status">正在加载信息流…</div>
      )}
      {trackingError && <div className="zr-status">{trackingError}</div>}

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
          key={entry.item.news_id}
          item={entry.item}
          userId={selectedPersona.user_id}
          requestId={entry.requestId}
          showReason
          onTrackClick={() => handleClick(entry)}
          onProfileChanged={bumpProfile}
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
