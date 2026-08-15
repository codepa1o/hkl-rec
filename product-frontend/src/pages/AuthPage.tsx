import { Eye, EyeOff } from "lucide-react";
import { type FormEvent, useEffect, useState } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

type Mode = "login" | "register";

export default function AuthPage() {
  const location = useLocation();
  const { user, loading, error, login, register, clearError } = useAuth();
  const [mode, setMode] = useState<Mode>("login");
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);

  useEffect(() => {
    clearError();
  }, [clearError]);

  const requestedPath = (location.state as { from?: { pathname?: string } } | null)?.from
    ?.pathname;
  if (user) return <Navigate to={requestedPath || "/"} replace />;

  const switchMode = () => {
    setMode((current) => (current === "login" ? "register" : "login"));
    clearError();
  };

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    try {
      if (mode === "register") {
        await register({ display_name: displayName.trim(), email: email.trim(), password });
      } else {
        await login({ email: email.trim(), password });
      }
    } catch {
      // AuthContext owns the user-facing error state.
    }
  };

  return (
    <main className="zr-auth-page">
      <section className="zr-auth-story" aria-label="产品介绍">
        <a className="zr-auth-brand" href="/" aria-label="新闻意图推荐">
          <span className="zr-auth-brand__mark">N</span>
          <span>新闻意图推荐</span>
        </a>
        <div className="zr-auth-story__copy">
          <p className="zr-auth-eyebrow">NEWS · INTENT · CONTEXT</p>
          <h1>继续你的阅读脉络</h1>
          <p>让每一次搜索、停留与选择，逐渐形成真正属于你的新闻视野。</p>
        </div>
        <p className="zr-auth-story__note">你的兴趣会变化，推荐也应当如此。</p>
      </section>

      <section className="zr-auth-panel">
        <div className="zr-auth-form-wrap">
          <div className="zr-auth-form-head">
            <p className="zr-auth-kicker">{mode === "login" ? "欢迎回来" : "建立你的阅读档案"}</p>
            <h2>{mode === "login" ? "登录账号" : "创建账号"}</h2>
            <p>{mode === "login" ? "从上次离开的地方继续。" : "只需一步，开始积累个性化兴趣。"}</p>
          </div>

          <form className="zr-auth-form" onSubmit={(event) => void submit(event)}>
            {mode === "register" && (
              <label className="zr-auth-field">
                <span>显示名称</span>
                <input
                  autoComplete="name"
                  minLength={2}
                  maxLength={40}
                  onChange={(event) => setDisplayName(event.target.value)}
                  placeholder="你希望我们如何称呼你"
                  required
                  value={displayName}
                />
              </label>
            )}

            <label className="zr-auth-field">
              <span>邮箱</span>
              <input
                autoComplete="email"
                onChange={(event) => setEmail(event.target.value)}
                placeholder="reader@example.com"
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
                  minLength={8}
                  maxLength={128}
                  onChange={(event) => setPassword(event.target.value)}
                  placeholder="至少 8 个字符"
                  required
                  type={showPassword ? "text" : "password"}
                  value={password}
                />
                <button
                  aria-label={showPassword ? "隐藏密码" : "显示密码"}
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

            <button className="zr-auth-submit" disabled={loading} type="submit">
              {loading ? "请稍候…" : mode === "login" ? "登录" : "完成注册"}
            </button>
          </form>

          <div className="zr-auth-switch">
            <span>{mode === "login" ? "第一次来到这里？" : "已经拥有账号？"}</span>
            <button onClick={switchMode} type="button">
              {mode === "login" ? "创建账号" : "返回登录"}
            </button>
          </div>
        </div>
      </section>
    </main>
  );
}
