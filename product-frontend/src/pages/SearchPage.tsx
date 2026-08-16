import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocation, useSearchParams } from "react-router-dom";
import { postSearch, stableClientId, trackEvent } from "../api/client";
import type { SearchItem } from "../api/types";
import { usePersona } from "../context/PersonaContext";
import PostCard from "../components/PostCard";
import SearchBox from "../components/SearchBox";
import { localizeInterfaceError } from "../localization";

export default function SearchPage() {
  const { selectedPersona, bumpProfile } = usePersona();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const rawQuery = searchParams.get("q") ?? "";
  const isExact = searchParams.get("exact") === "1";
  const [items, setItems] = useState<SearchItem[]>([]);
  const [resolvedQueryKey, setResolvedQueryKey] = useState<string>("");
  const [requestId, setRequestId] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const searchEventId = useMemo(
    () =>
      stableClientId(
        "search",
        `${location.key}:${selectedPersona?.user_id ?? "none"}:${rawQuery}:${isExact}`,
      ),
    [location.key, selectedPersona?.user_id, rawQuery, isExact],
  );

  useEffect(() => {
    if (!selectedPersona || !rawQuery) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setItems([]);
    setResolvedQueryKey("");
    const input = isExact ? { queryKey: rawQuery } : { queryText: rawQuery };
    postSearch(selectedPersona.user_id, input, 10, searchEventId)
      .then((res) => {
        if (cancelled) return;
        setItems(res.items);
        setResolvedQueryKey(res.query_key);
        setRequestId(res.request_id);
        bumpProfile();
      })
      .catch((err: Error) => {
        if (cancelled) return;
        if (err.message.startsWith("422")) {
          setError("未找到匹配内容，请尝试搜索建议中的关键词。");
        } else {
          setError(localizeInterfaceError(err.message));
        }
      })
      .finally(() => {
        if (cancelled) return;
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedPersona, rawQuery, isExact, bumpProfile, searchEventId]);

  const handleClick = useCallback(
    (newsId: string) => {
      if (!selectedPersona) return;
      trackEvent({
        event_id: `search-click-${requestId}:${newsId}`,
        user_id: selectedPersona.user_id,
        event_type: "search_result_click",
        surface: "search",
        news_id: newsId,
        query_key: resolvedQueryKey || rawQuery,
        request_id: requestId || searchEventId,
      }).then(() => bumpProfile());
    },
    [selectedPersona, resolvedQueryKey, rawQuery, requestId, searchEventId, bumpProfile],
  );

  if (!selectedPersona) {
    return (
      <main className="zr-center">
        <div className="zr-status">请选择一个用户画像后再搜索。</div>
      </main>
    );
  }

  return (
    <main className="zr-center zr-search-page">
      <header className="zr-page-header">
        <span className="zr-eyebrow">发现内容</span>
        <h1>搜索</h1>
        <p>查找你关心的新闻、主题与领域</p>
      </header>

      <div className="zr-search-page__box">
        <SearchBox initialQuery={rawQuery} />
      </div>

      {rawQuery && (
        <div className="zr-search-page__result-label">
          “<strong>{rawQuery}</strong>”的搜索结果
        </div>
      )}

      {!rawQuery && (
        <div className="zr-status zr-status--spacious">
          输入关键词，开始探索你的下一篇阅读。
        </div>
      )}

      {loading && <div className="zr-status">正在搜索…</div>}
      {error && <div className="zr-status">搜索失败：{error}</div>}

      {!loading && !error && rawQuery && items.length === 0 && (
        <div className="zr-status">未找到与“{rawQuery}”相关的结果。</div>
      )}

      {items.map((item) => (
        <PostCard
          key={item.news_id}
          item={item}
          userId={selectedPersona.user_id}
          surface="search"
          onTrackClick={() => handleClick(item.news_id)}
          onProfileChanged={bumpProfile}
        />
      ))}
    </main>
  );
}
