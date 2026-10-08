import { useState } from "react";
import type { LiveLanguage } from "../api/types";
import { saveSearch } from "./api";
import { useReading } from "./ReadingContext";

export default function SavedSearchButton({ query, language, category }: { query: string; language: LiveLanguage; category: string | null }) {
  const reading = useReading();
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState(false);
  if (!reading?.active || !query.trim()) return null;
  const save = async () => {
    setPending(true); setMessage(""); setError(false);
    try { await saveSearch({ source_space: reading.sourceSpace, query, language, category }); setMessage("搜索已保存"); }
    catch (err) { setError(true); setMessage(err instanceof Error ? err.message : "搜索保存失败"); }
    finally { setPending(false); }
  };
  return <div className="zr-reading-actions"><button type="button" disabled={pending} onClick={() => void save()}>保存此搜索</button>{message && <span role={error ? "alert" : "status"}>{message}</span>}</div>;
}
