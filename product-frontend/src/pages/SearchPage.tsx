import { useCallback, useEffect, useMemo, useState } from "react";
import { useLocation, useSearchParams } from "react-router-dom";
import { postSearch, stableClientId, trackEvent } from "../api/client";
import type { SearchItem } from "../api/types";
import { usePersona } from "../context/PersonaContext";
import { useSourceSpace } from "../context/SourceSpaceContext";
import PostCard from "../components/PostCard";
import SearchBox from "../components/SearchBox";
import { localizeInterfaceError } from "../localization";
import SavedSearchButton from "../reading/SavedSearchButton";
import { useReading } from "../reading/ReadingContext";
import { searchReading } from "../reading/api";

export default function SearchPage() {
  const { selectedPersona, bumpProfile } = usePersona();
  const { sourceSpace } = useSourceSpace();
  const reading = useReading();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  const rawQuery = searchParams.get("q") ?? "";
  const requestedSpace = searchParams.get("space");
  const effectiveSpace = requestedSpace === "mind" || requestedSpace === "live" ? requestedSpace : sourceSpace;
  const savedSearchMode = Boolean(reading?.active && requestedSpace === effectiveSpace);
  const searchLanguage = searchParams.get("language") === "zh" || searchParams.get("language") === "en" ? searchParams.get("language") as "zh" | "en" : "all";
  const searchCategory = searchParams.get("category");
  const isExact = searchParams.get("exact") === "1";
  const [items, setItems] = useState<SearchItem[]>([]);
  const [resolvedQueryKey, setResolvedQueryKey] = useState<string>("");
  const [requestId, setRequestId] = useState<string>("");
  const [hiddenCount, setHiddenCount] = useState(0);
  const [includeHidden, setIncludeHidden] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const searchEventId = useMemo(
    () =>
      stableClientId(
        "search",
        `${location.key}:${effectiveSpace}:${selectedPersona?.user_id ?? "none"}:${rawQuery}:${isExact}`,
      ),
    [location.key, effectiveSpace, selectedPersona?.user_id, rawQuery, isExact],
  );

  useEffect(() => {
    if (!selectedPersona || !rawQuery) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setItems([]);
    setResolvedQueryKey("");
    setRequestId("");
    setHiddenCount(0);
    const input = isExact ? { queryKey: rawQuery } : { queryText: rawQuery };
    (savedSearchMode
      ? searchReading(effectiveSpace, rawQuery, searchLanguage, searchCategory, includeHidden, searchEventId)
      : postSearch(selectedPersona.user_id, input, 10, searchEventId, effectiveSpace))
      .then((res) => {
        if (cancelled || res.source_space !== effectiveSpace) return;
        setItems(res.items);
        setResolvedQueryKey(res.query_key);
        setRequestId(res.request_id);
        setHiddenCount("hidden_count" in res ? Number(res.hidden_count) : 0);
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
  }, [selectedPersona, rawQuery, isExact, bumpProfile, searchEventId, effectiveSpace, savedSearchMode, searchLanguage, searchCategory, includeHidden]);

  const handleClick = useCallback(
    (articleId: string) => {
      if (!selectedPersona) return;
      trackEvent({
        event_id: `search-click-${sourceSpace}:${requestId}:${articleId}`,
        user_id: selectedPersona.user_id,
        source_space: effectiveSpace,
        event_type: "search_result_click",
        surface: "search",
        article_id: articleId,
        query_key: resolvedQueryKey || rawQuery,
        request_id: requestId || searchEventId,
      }).then(() => bumpProfile());
    },
    [
      selectedPersona,
      effectiveSpace,
      resolvedQueryKey,
      rawQuery,
      requestId,
      searchEventId,
      bumpProfile,
    ],
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

      {rawQuery && <SavedSearchButton query={rawQuery} language={searchLanguage} category={searchCategory} />}
      {savedSearchMode && hiddenCount > 0 && !includeHidden && (
        <button type="button" className="zr-reading-actions" onClick={() => setIncludeHidden(true)}>
          还有 {hiddenCount} 条结果被偏好规则隐藏，仍然查看
        </button>
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
          key={item.article_id}
          item={item}
          userId={selectedPersona.user_id}
          surface="search"
          onTrackClick={() => handleClick(item.article_id)}
          onProfileChanged={bumpProfile}
        />
      ))}
    </main>
  );
}
