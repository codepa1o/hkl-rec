import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation } from "react-router-dom";
import { getFeed, stableClientId, trackEvent } from "../api/client";
import type { FeedItem } from "../api/types";
import { usePersona } from "../context/PersonaContext";
import PostCard from "../components/PostCard";
import { localizeInterfaceError } from "../localization";

export default function FeedPage() {
  const { selectedPersona, refreshTick, bumpProfile } = usePersona();
  const location = useLocation();
  const [items, setItems] = useState<FeedItem[]>([]);
  const [feedUserId, setFeedUserId] = useState<number | null>(null);
  const [requestId, setRequestId] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [trackingError, setTrackingError] = useState<string | null>(null);
  const trackedRef = useRef<Set<string>>(new Set());
  const loadRequestId = useMemo(
    () =>
      stableClientId(
        "feed",
        `${location.key}:${selectedPersona?.user_id ?? "none"}:${refreshTick}`,
      ),
    [location.key, selectedPersona?.user_id, refreshTick],
  );

  useEffect(() => {
    if (!selectedPersona) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setItems([]);
    setRequestId("");
    setFeedUserId(null);
    getFeed(selectedPersona.user_id, 10, true, loadRequestId)
      .then((res) => {
        if (cancelled) return;
        setItems(res.items);
        setRequestId(res.request_id);
        setFeedUserId(res.user_id);
      })
      .catch((err: Error) => {
        if (cancelled) return;
        setError(err.message);
      })
      .finally(() => {
        if (cancelled) return;
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedPersona, refreshTick, loadRequestId]);

  useEffect(() => {
    if (
      !selectedPersona ||
      feedUserId !== selectedPersona.user_id ||
      !requestId ||
      items.length === 0
    ) {
      return;
    }
    const pending = items
      .map((item) => ({
        item,
        key: `${selectedPersona.user_id}:${requestId}:${item.article_id}`,
      }))
      .filter(({ key }) => !trackedRef.current.has(key));
    if (pending.length === 0) return;

    pending.forEach(({ key }) => trackedRef.current.add(key));
    setTrackingError(null);
    void Promise.allSettled(
      pending.map(({ item, key }) =>
        trackEvent({
          event_id: `imp-${key}`,
          user_id: selectedPersona.user_id,
          event_type: "feed_impression",
          surface: "feed",
          article_id: item.article_id,
          request_id: requestId,
          sponsored_delivery_id: item.sponsored?.delivery_id ?? null,
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
        setTrackingError(`有 ${failedKeys.length} 条内容的曝光记录失败，请稍后重试。`);
      }
    });
  }, [selectedPersona, feedUserId, requestId, items]);

  const visibleItems =
    selectedPersona && feedUserId === selectedPersona.user_id ? items : [];

  const handleClick = useCallback(
    (item: FeedItem) => {
      if (!selectedPersona) return;
      const articleId = item.article_id;
      void trackEvent({
        event_id: `click-${selectedPersona.user_id}:${requestId}:${articleId}`,
        user_id: selectedPersona.user_id,
        event_type: "recommendation_click",
        surface: "feed",
        article_id: articleId,
        request_id: requestId,
        sponsored_delivery_id: item.sponsored?.delivery_id ?? null,
      })
        .then(() => {
          setTrackingError(null);
          bumpProfile();
        })
        .catch((err: Error) => setTrackingError(`点击记录失败：${localizeInterfaceError(err.message)}`));
    },
    [selectedPersona, requestId, bumpProfile],
  );

  if (!selectedPersona) {
    return <div className="zr-status">请选择一个用户画像以查看推荐信息流。</div>;
  }
  if (error) {
    return <div className="zr-status">信息流加载失败：{localizeInterfaceError(error)}</div>;
  }

  return (
    <main className="zr-center">
      <header className="zr-page-header">
        <span className="zr-eyebrow">你的每日阅读</span>
        <h1>为你推荐</h1>
        <p>根据你的阅读兴趣持续更新</p>
      </header>

      {loading && visibleItems.length === 0 && <div className="zr-status">正在加载信息流…</div>}
      {trackingError && <div className="zr-status">{trackingError}</div>}

      {!loading && visibleItems.length === 0 && (
        <div className="zr-status">当前信息流暂无文章，请尝试选择其他用户画像。</div>
      )}

      {visibleItems.map((item) => (
        <PostCard
          key={item.article_id}
          item={item}
          userId={selectedPersona.user_id}
          requestId={requestId}
          showReason
          onTrackClick={() => handleClick(item)}
          onProfileChanged={bumpProfile}
        />
      ))}
    </main>
  );
}
