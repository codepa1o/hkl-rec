import { Eye, EyeOff } from "lucide-react";
import { useReducedMotion } from "motion/react";
import {
  type FormEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { Navigate, useLocation } from "react-router-dom";
import AuthCinematicStage, {
  type AuthMode,
  type AuthPhase,
} from "../components/AuthCinematicStage";
import { useAuth } from "../context/AuthContext";

const ENTRY_DURATION_MS = 700;
const SWITCH_CONTENT_DELAY_MS = 330;
const SUCCESS_EXIT_DELAY_MS = 680;
const ERROR_SETTLE_DELAY_MS = 240;

export default function AuthPage() {
  const location = useLocation();
  const { user, loading, error, login, register, clearError } = useAuth();
  const reducedMotion = useReducedMotion() ?? false;
  const [mode, setMode] = useState<AuthMode>("login");
  const [phase, setPhase] = useState<AuthPhase>(reducedMotion ? "idle" : "entering");
  const [shouldNavigate, setShouldNavigate] = useState(false);
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const timersRef = useRef(new Set<number>());
  const submittedHereRef = useRef(false);
  const requestGenerationRef = useRef(0);
  const reducedMotionRef = useRef(reducedMotion);
  const focusAfterSwitchRef = useRef(false);
  const displayNameRef = useRef<HTMLInputElement>(null);
  const emailRef = useRef<HTMLInputElement>(null);
  reducedMotionRef.current = reducedMotion;

  const clearTimers = useCallback(() => {
    timersRef.current.forEach((timer) => window.clearTimeout(timer));
    timersRef.current.clear();
  }, []);

  const schedule = useCallback((callback: () => void, delay: number) => {
    const timer = window.setTimeout(() => {
      timersRef.current.delete(timer);
      callback();
    }, delay);
    timersRef.current.add(timer);
    return timer;
  }, []);

  useEffect(() => {
    clearError();
  }, [clearError]);

  useEffect(() => {
    if (reducedMotion) {
      setPhase((current) => (current === "entering" ? "idle" : current));
      return;
    }

    const entryTimer = schedule(() => {
      setPhase((current) => (current === "entering" ? "idle" : current));
    }, ENTRY_DURATION_MS);
    return () => {
      window.clearTimeout(entryTimer);
      timersRef.current.delete(entryTimer);
    };
  }, [reducedMotion, schedule]);

  useEffect(
    () => () => {
      requestGenerationRef.current += 1;
      clearTimers();
    },
    [clearTimers],
  );

  useEffect(() => {
    if (!reducedMotion || phase !== "success") return;

    clearTimers();
    setShouldNavigate(true);
  }, [clearTimers, phase, reducedMotion]);

  useEffect(() => {
    if (phase !== "idle" || !focusAfterSwitchRef.current) return;

    focusAfterSwitchRef.current = false;
    const target = mode === "register" ? displayNameRef.current : emailRef.current;
    target?.focus();
  }, [mode, phase]);

  const requestedPath = (location.state as { from?: { pathname?: string } } | null)?.from
    ?.pathname;
  if (shouldNavigate || (user && !submittedHereRef.current)) {
    return <Navigate to={requestedPath || "/"} replace />;
  }

  const isInteractionLocked =
    loading || phase === "switching" || phase === "submitting" || phase === "success";

  const switchMode = () => {
    if (isInteractionLocked) return;

    clearTimers();
    clearError();
    setPhase("switching");
    const nextMode: AuthMode = mode === "login" ? "register" : "login";
    const commitMode = () => {
      setMode(nextMode);
      focusAfterSwitchRef.current = true;
    };

    if (reducedMotion) {
      commitMode();
      setPhase("idle");
      return;
    }

    schedule(commitMode, SWITCH_CONTENT_DELAY_MS);
    schedule(() => setPhase("idle"), ENTRY_DURATION_MS);
  };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (isInteractionLocked) return;

    clearTimers();
    clearError();
    submittedHereRef.current = true;
    const requestGeneration = ++requestGenerationRef.current;
    setPhase("submitting");

    try {
      if (mode === "register") {
        await register({ display_name: displayName.trim(), email: email.trim(), password });
      } else {
        await login({ email: email.trim(), password });
      }

      if (requestGeneration !== requestGenerationRef.current) return;

      setPhase("success");
      if (reducedMotionRef.current) {
        setShouldNavigate(true);
      } else {
        schedule(() => setShouldNavigate(true), SUCCESS_EXIT_DELAY_MS);
      }
    } catch {
      if (requestGeneration !== requestGenerationRef.current) return;

      submittedHereRef.current = false;
      setPhase("error");
      schedule(
        () => setPhase("idle"),
        reducedMotionRef.current ? 0 : ERROR_SETTLE_DELAY_MS,
      );
      // AuthContext owns the user-facing error state.
    }
  };

  const submitLabel =
    phase === "submitting"
      ? mode === "login"
        ? "正在登录…"
        : "正在创建…"
      : mode === "login"
        ? "登录"
        : "完成注册";

  return (
    <AuthCinematicStage mode={mode} phase={phase} reducedMotion={reducedMotion}>
      <div className="zr-auth-form-head">
        <p className="zr-auth-kicker">{mode === "login" ? "欢迎回来" : "建立你的阅读档案"}</p>
        <h2>{mode === "login" ? "登录账号" : "创建账号"}</h2>
        <p>{mode === "login" ? "从上次离开的地方继续。" : "只需一步，开始积累个性化兴趣。"}</p>
      </div>

      <form
        aria-busy={phase === "submitting"}
        className="zr-auth-form"
        onSubmit={(event) => void submit(event)}
      >
        {mode === "register" && (
          <label className="zr-auth-field">
            <span>显示名称</span>
            <input
              autoComplete="name"
              disabled={isInteractionLocked}
              maxLength={40}
              minLength={2}
              onChange={(event) => setDisplayName(event.target.value)}
              placeholder="你希望我们如何称呼你"
              ref={displayNameRef}
              required
              value={displayName}
            />
          </label>
        )}

        <label className="zr-auth-field">
          <span>邮箱</span>
          <input
            autoComplete="email"
            disabled={isInteractionLocked}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="reader@example.com"
            ref={emailRef}
            required
            type="email"
            value={email}
          />
        </label>

        <label className="zr-auth-field">
          <span>密码</span>
          <span className="zr-auth-password">
            <input
              autoComplete={mode === "login" ? "current-password" : "new-password"}
              disabled={isInteractionLocked}
              maxLength={128}
              minLength={8}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="至少 8 个字符"
              required
              type={showPassword ? "text" : "password"}
              value={password}
            />
            <button
              aria-label={showPassword ? "隐藏密码" : "显示密码"}
              disabled={isInteractionLocked}
              onClick={() => setShowPassword((visible) => !visible)}
              type="button"
            >
              {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
            </button>
          </span>
        </label>

        {error && (
          <p className="zr-auth-error" role="alert">
            {error}
          </p>
        )}

        <button className="zr-auth-submit" disabled={isInteractionLocked} type="submit">
          <span>{submitLabel}</span>
        </button>
      </form>

      <div className="zr-auth-switch">
        <span>{mode === "login" ? "第一次来到这里？" : "已经拥有账号？"}</span>
        <button disabled={isInteractionLocked} onClick={switchMode} type="button">
          {mode === "login" ? "创建账号" : "返回登录"}
        </button>
      </div>
    </AuthCinematicStage>
  );
}
