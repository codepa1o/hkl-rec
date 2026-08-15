import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { listPersonas } from "../api/client";
import type { PersonaCard } from "../api/types";
import { useAuth } from "./AuthContext";

interface PersonaContextValue {
  personas: PersonaCard[];
  selectedPersona: PersonaCard | null;
  selectPersona: (userId: number) => void;
  loading: boolean;
  error: string | null;
  refreshTick: number;
  bumpProfile: () => void;
}

const PersonaContext = createContext<PersonaContextValue | null>(null);

export function PersonaProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const [personas, setPersonas] = useState<PersonaCard[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshTick, setRefreshTick] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    listPersonas(10)
      .then((res) => {
        if (cancelled) return;
        const accountPersona: PersonaCard | null = user
          ? {
              user_id: user.user_id,
              display_name: user.display_name,
              behavior_score: 0,
              top_topics: [],
            }
          : null;
        const items = accountPersona
          ? [accountPersona, ...res.items.filter((item) => item.user_id !== accountPersona.user_id)]
          : res.items;
        setPersonas(items);
        setSelectedId(accountPersona?.user_id ?? items[0]?.user_id ?? null);
        setError(null);
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
  }, [user]);

  const selectPersona = useCallback((userId: number) => {
    setSelectedId(userId);
    setRefreshTick((tick) => tick + 1);
  }, []);

  const bumpProfile = useCallback(() => {
    setRefreshTick((tick) => tick + 1);
  }, []);

  const selectedPersona = useMemo(
    () => personas.find((p) => p.user_id === selectedId) ?? null,
    [personas, selectedId],
  );

  const value = useMemo<PersonaContextValue>(
    () => ({ personas, selectedPersona, selectPersona, loading, error, refreshTick, bumpProfile }),
    [personas, selectedPersona, selectPersona, loading, error, refreshTick, bumpProfile],
  );

  return <PersonaContext.Provider value={value}>{children}</PersonaContext.Provider>;
}

export function usePersona(): PersonaContextValue {
  const ctx = useContext(PersonaContext);
  if (!ctx) throw new Error("usePersona must be used inside PersonaProvider");
  return ctx;
}
