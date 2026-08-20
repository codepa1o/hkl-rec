import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { listNewsSpaces } from "../api/client";
import type { NewsSpace } from "../api/types";

const STORAGE_KEY = "newsrec:source-space";

interface SourceSpaceContextValue {
  sourceSpace: NewsSpace;
  liveEnabled: boolean;
  loading: boolean;
  selectSourceSpace: (sourceSpace: NewsSpace) => void;
}

const SourceSpaceContext = createContext<SourceSpaceContextValue | null>(null);

export function SourceSpaceProvider({ children }: { children: ReactNode }) {
  const [sourceSpace, setSourceSpace] = useState<NewsSpace>(() =>
    localStorage.getItem(STORAGE_KEY) === "live" ? "live" : "mind",
  );
  const [liveEnabled, setLiveEnabled] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    listNewsSpaces()
      .then((response) => {
        if (cancelled) return;
        const enabled = response.items.some(
          (item) => item.source_space === "live" && item.enabled,
        );
        setLiveEnabled(enabled);
        if (!enabled) {
          setSourceSpace("mind");
          localStorage.setItem(STORAGE_KEY, "mind");
        }
      })
      .catch(() => {
        if (cancelled) return;
        setLiveEnabled(false);
        setSourceSpace("mind");
        localStorage.setItem(STORAGE_KEY, "mind");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const selectSourceSpace = useCallback(
    (nextSpace: NewsSpace) => {
      const selected = nextSpace === "live" && !liveEnabled ? "mind" : nextSpace;
      setSourceSpace(selected);
      localStorage.setItem(STORAGE_KEY, selected);
    },
    [liveEnabled],
  );

  const value = useMemo(
    () => ({ sourceSpace, liveEnabled, loading, selectSourceSpace }),
    [sourceSpace, liveEnabled, loading, selectSourceSpace],
  );
  return <SourceSpaceContext.Provider value={value}>{children}</SourceSpaceContext.Provider>;
}

export function useSourceSpace(): SourceSpaceContextValue {
  const context = useContext(SourceSpaceContext);
  if (!context) throw new Error("useSourceSpace must be used inside SourceSpaceProvider");
  return context;
}
