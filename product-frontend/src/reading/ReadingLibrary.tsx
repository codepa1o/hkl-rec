import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { deleteSavedSearch, getLibrary, getSavedSearches, type LibraryItem, type SavedSearch } from "./api";
import { useReading } from "./ReadingContext";
import ReadingActions from "./ReadingActions";

export function savedSearchHref(search: SavedSearch): string {
  const params = new URLSearchParams({ q: search.query, space: search.source_space });
  if (search.language !== "all") params.set("language", search.language);
  if (search.category) params.set("category", search.category);
  return `/search?${params}`;
}
export default function ReadingLibrary() {
  const reading = useReading();
  const [items, setItems] = useState<LibraryItem[]>([]);
  const [searches, setSearches] = useState<SavedSearch[]>([]);
  const [unreadOnly, setUnreadOnly] = useState(false);
  const [hasMore, setHasMore] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  const version = useRef(0);
  useEffect(() => {
    if (!reading) return;
    const current = ++version.current;
    setPending(true); setError(null); setItems([]); setSearches([]);
    Promise.all([getLibrary(reading.sourceSpace, unreadOnly), getSavedSearches(reading.sourceSpace)])
      .then(([library, saved]) => { if (current === version.current) { setItems(library.items); setHasMore(library.has_more); setSearches(saved.items); } })
      .catch((err: Error) => { if (current === version.current) setError(err.message); })
      .finally(() => { if (current === version.current) setPending(false); });
    return () => { version.current++; };
  }, [reading?.sourceSpace, reading?.accountId, unreadOnly, refresh]);
  if (!reading) return null;
  const visibleItems = items.filter((item) => {
    const state = reading.states[item.article_id];
    return state?.saved !== false && (!unreadOnly || state?.read !== true);
  });
  const more = async () => {
    const current = version.current; setPending(true); setError(null);
    try { const response = await getLibrary(reading.sourceSpace, unreadOnly, items.length); if (current === version.current) { setItems((previous) => [...previous, ...response.items]); setHasMore(response.has_more); } }
    catch (err) { if (current === version.current) setError(err instanceof Error ? err.message : "加载失败"); }
    finally { if (current === version.current) setPending(false); }
  };
  const removeSearch = async (id: number) => {
    setPending(true); setError(null);
    try { await deleteSavedSearch(reading.sourceSpace, id); setSearches((previous) => previous.filter((item) => item.id !== id)); }
    catch (err) { setError(err instanceof Error ? err.message : "删除失败"); }
    finally { setPending(false); }
  };
  return <main className="zr-center zr-reading-page">
    <header className="zr-page-header"><span className="zr-eyebrow">属于你的阅读清单</span><h1>我的阅读</h1><p>{reading.sourceSpace === "mind" ? "MIND" : "实时新闻"}空间 · 当前登录账号的收藏与保存搜索</p></header>
    <section className="zr-reading-panel"><h2>保存的搜索</h2>
      {!searches.length && !pending && <p>在搜索结果页保存关键词，下次可直接继续查看。</p>}
      <ul className="zr-reading-list">{searches.map((search) => <li key={search.id}><Link to={savedSearchHref(search)}>{search.query}</Link><button type="button" disabled={pending} onClick={() => void removeSearch(search.id)}>删除搜索</button></li>)}</ul>
    </section>
    <section className="zr-reading-panel"><h2>收藏文章</h2>
      <div className="zr-reading-actions"><label><input type="checkbox" checked={unreadOnly} onChange={(e) => setUnreadOnly(e.target.checked)} />只看未读</label><button type="button" disabled={pending} onClick={() => setRefresh((n) => n + 1)}>刷新列表</button></div>
      {error && <p role="alert">{error}<button type="button" onClick={() => setRefresh((n) => n + 1)}>重试</button></p>}
      {visibleItems.map((item) => <article className="zr-reading-entry" key={item.article_id}>
        <small>{item.source_domain}</small>
        <h3>{item.available ? <Link to={`/articles/${item.source_space}/${item.article_id}`}>{item.title}</Link> : item.title}</h3>
        {!item.available && <p>文章已不可用，收藏记录仍保留</p>}
        <ReadingActions sourceSpace={item.source_space} articleId={item.article_id} personal />
      </article>)}
      {pending && <p role="status">正在加载…</p>}
      {!visibleItems.length && !pending && !error && <p>{unreadOnly ? "暂无未读的收藏文章。" : "还没有收藏文章。在新闻卡片或详情页点击收藏即可保存。"}</p>}
      {hasMore && <button type="button" disabled={pending} onClick={() => void more()}>加载更多收藏</button>}
    </section>
  </main>;
}
