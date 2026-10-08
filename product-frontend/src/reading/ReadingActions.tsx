import { Bookmark, BookOpen, Check } from "lucide-react";
import { useEffect, useState } from "react";
import type { NewsSpace } from "../api/types";
import { useReading } from "./ReadingContext";

export default function ReadingActions({ sourceSpace, articleId, personal = false }: { sourceSpace: NewsSpace; articleId: string; personal?: boolean }) {
  const reading = useReading();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const enabled = Boolean(reading && (reading.active || personal) && reading.sourceSpace === sourceSpace);
  const ensure = reading?.ensure;
  useEffect(() => { if (enabled) ensure?.(articleId); }, [articleId, ensure, enabled]);
  if (!reading || !enabled) return null;
  const state = reading.states[articleId];
  const change = async (field: "saved" | "read") => {
    if (!state || pending) return;
    setPending(true); setError(null);
    try { await reading.update(articleId, { [field]: !state[field] }); }
    catch (err) { setError(err instanceof Error ? err.message : "保存失败，请重试"); }
    finally { setPending(false); }
  };
  return <div className="zr-reading-actions">
    <button type="button" className="zr-action" aria-label={state?.saved ? "取消收藏" : "收藏文章"} aria-pressed={state?.saved ?? false} disabled={!state || pending} onClick={() => void change("saved")}><Bookmark size={15} />{state?.saved ? "已收藏" : "收藏"}</button>
    <button type="button" className="zr-action" aria-label={state?.read ? "标为未读" : "标为已读"} aria-pressed={state?.read ?? false} disabled={!state || pending} onClick={() => void change("read")}>{state?.read ? <Check size={15} /> : <BookOpen size={15} />}{state?.read ? "已读" : "标为已读"}</button>
    {error && <span role="alert">{error}</span>}
    {!state && reading.stateError && <span role="alert">{reading.stateError}<button type="button" onClick={() => reading.ensure(articleId)}>重试</button></span>}
  </div>;
}
