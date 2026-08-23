import {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from "react";
import {
  getCurrentUser,
  login as loginRequest,
  logout as logoutRequest,
  register as registerRequest,
  UNAUTHORIZED_EVENT,
} from "../api/client";
import type { AuthUser, LoginInput, RegisterInput } from "../api/types";
import { clearFeedSessionData } from "../feed/feedSessionStore";

interface AuthContextValue {
  user: AuthUser | null;
  loading: boolean;
  error: string | null;
  login: (payload: LoginInput) => Promise<void>;
  register: (payload: RegisterInput) => Promise<void>;
  logout: () => Promise<void>;
  clearError: () => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "请求失败，请稍后重试";
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    getCurrentUser()
      .then((currentUser) => {
        if (active) setUser(currentUser);
      })
      .catch(() => {
        if (active) setUser(null);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    const clearExpiredSession = () => {
      clearFeedSessionData();
      setUser(null);
    };
    globalThis.addEventListener(UNAUTHORIZED_EVENT, clearExpiredSession);
    return () => globalThis.removeEventListener(UNAUTHORIZED_EVENT, clearExpiredSession);
  }, []);

  const runAuth = useCallback(
    async (request: () => Promise<AuthUser>) => {
      setLoading(true);
      setError(null);
      try {
        setUser(await request());
      } catch (requestError) {
        setError(errorMessage(requestError));
        throw requestError;
      } finally {
        setLoading(false);
      }
    },
    [],
  );

  const login = useCallback(
    (payload: LoginInput) => runAuth(() => loginRequest(payload)),
    [runAuth],
  );
  const register = useCallback(
    (payload: RegisterInput) => runAuth(() => registerRequest(payload)),
    [runAuth],
  );
  const logout = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      await logoutRequest();
      clearFeedSessionData();
      setUser(null);
    } catch (requestError) {
      setError(errorMessage(requestError));
      throw requestError;
    } finally {
      setLoading(false);
    }
  }, []);
  const clearError = useCallback(() => setError(null), []);

  const value = useMemo(
    () => ({ user, loading, error, login, register, logout, clearError }),
    [user, loading, error, login, register, logout, clearError],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside AuthProvider");
  return context;
}
