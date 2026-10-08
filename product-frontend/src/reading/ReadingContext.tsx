import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { useAuth } from "../context/AuthContext";
import { usePersona } from "../context/PersonaContext";
import { useSourceSpace } from "../context/SourceSpaceContext";
import { FEED_SESSION_STORAGE_KEY } from "../feed/feedSessionStore";
import type { NewsSpace } from "../api/types";
import { getReadingStates, getRules, updateReadingState, type PreferenceRule, type ReadingState } from "./api";

interface ReadingContextValue {
  active: boolean; accountId: number; sourceSpace: NewsSpace;
  states: Record<string, ReadingState>; stateError: string | null; rules: PreferenceRule[];
  revision: number; readRevision: number;
  ensure: (articleId: string) => void;
  update: (articleId: string, change: Partial<Pick<ReadingState, "saved" | "read">>) => Promise<void>;
  preferencesChanged: () => void;
}
const ReadingContext = createContext<ReadingContextValue | null>(null);
const revisionKey = (accountId: number, sourceSpace: NewsSpace, kind: string) => `newsrec:reading-revision:${accountId}:${sourceSpace}:${kind}`;
function readStoredRevision(accountId: number, sourceSpace: NewsSpace, kind: string): number {
  try { const value = Number(localStorage.getItem(revisionKey(accountId, sourceSpace, kind))); return Number.isSafeInteger(value) && value >= 0 ? value : 0; }
  catch { return 0; }
}
function writeRevision(accountId: number, sourceSpace: NewsSpace, kind: string, value: number): void {
  try { localStorage.setItem(revisionKey(accountId, sourceSpace, kind), String(value)); } catch { /* Persistence is optional. */ }
}
export const useReading = () => useContext(ReadingContext);

export function ReadingProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const { sourceSpace } = useSourceSpace();
  const { selectedPersona } = usePersona();
  if (!user) return <>{children}</>;
  return <ReadingSession key={`${user.user_id}:${sourceSpace}`} accountId={user.user_id} sourceSpace={sourceSpace} active={selectedPersona?.user_id === user.user_id}>{children}</ReadingSession>;
}

function ReadingSession({ children, accountId, sourceSpace, active }: { children: ReactNode; accountId: number; sourceSpace: NewsSpace; active: boolean }) {
  const [states, setStates] = useState<Record<string, ReadingState>>({});
  const [rules, setRules] = useState<PreferenceRule[]>([]);
  const [stateError, setStateError] = useState<string | null>(null);
  const [revision, setRevision] = useState(() => readStoredRevision(accountId, sourceSpace, "rules"));
  const [readRevision, setReadRevision] = useState(() => readStoredRevision(accountId, sourceSpace, "state"));
  const pending = useRef(new Set<string>());
  const loaded = useRef(new Set<string>());
  const timer = useRef<ReturnType<typeof setTimeout>>();
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; clearTimeout(timer.current); }; }, []);
  const clearSnapshots = () => { try { sessionStorage.removeItem(FEED_SESSION_STORAGE_KEY); } catch { /* Storage is optional. */ } };
  useEffect(() => {
    let cancelled = false;
    getRules(sourceSpace).then((response) => { if (!cancelled) setRules(response.items); }).catch(() => undefined);
    return () => { cancelled = true; };
  }, [sourceSpace, revision]);
  const ensure = useCallback((id: string) => {
    if (loaded.current.has(id) || pending.current.has(id)) return;
    pending.current.add(id);
    clearTimeout(timer.current);
    timer.current = setTimeout(async () => {
      const ids = [...pending.current]; pending.current.clear();
      ids.forEach((value) => loaded.current.add(value));
      try {
        const batches = await Promise.all(Array.from({ length: Math.ceil(ids.length / 100) }, (_, index) => getReadingStates(sourceSpace, ids.slice(index * 100, index * 100 + 100))));
        if (!alive.current) return;
        setStates((current) => ({ ...current, ...Object.fromEntries(batches.flatMap((batch) => batch.items).map((item) => [item.article_id, item])) }));
        setStateError(null);
      } catch (error) {
        ids.forEach((value) => loaded.current.delete(value));
        if (alive.current) setStateError(error instanceof Error ? error.message : "阅读状态加载失败");
      }
    }, 0);
  }, [sourceSpace]);
  const update = useCallback(async (id: string, change: Partial<Pick<ReadingState, "saved" | "read">>) => {
    const result = await updateReadingState(sourceSpace, id, change);
    if (!alive.current) return;
    setStates((current) => ({ ...current, [id]: result }));
    clearSnapshots();
    setReadRevision((value) => { const next = value + 1; writeRevision(accountId, sourceSpace, "state", next); return next; });
  }, [accountId, sourceSpace]);
  const preferencesChanged = useCallback(() => { clearSnapshots(); setRevision((value) => { const next = value + 1; writeRevision(accountId, sourceSpace, "rules", next); return next; }); }, [accountId, sourceSpace]);
  return <ReadingContext.Provider value={{ active, accountId, sourceSpace, states, stateError, rules, revision, readRevision, ensure, update, preferencesChanged }}>{children}</ReadingContext.Provider>;
}
