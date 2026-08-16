import { ChevronDown, LogOut } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useAuth } from "../context/AuthContext";
import { usePersona } from "../context/PersonaContext";
import { localizePersonaName } from "../localization";
import SlidingSelectionGroup from "./SlidingSelectionGroup";

export default function AccountMenu() {
  const { user, logout } = useAuth();
  const { personas, selectedPersona, selectPersona, loading } = usePersona();
  const [open, setOpen] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);
  const [logoutError, setLogoutError] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;

    const handlePointerDown = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        triggerRef.current?.focus();
      }
    };

    document.addEventListener("mousedown", handlePointerDown);
    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("mousedown", handlePointerDown);
      document.removeEventListener("keydown", handleKeyDown);
    };
  }, [open]);

  if (!user) return null;

  const avatarText = Array.from(user.display_name.trim())[0] ?? "用";
  const menuLabel = open ? "关闭账号菜单" : "打开账号菜单";
  const selectedPersonaIndex = personas.findIndex(
    (persona) => persona.user_id === selectedPersona?.user_id,
  );

  const handleSelectPersona = (userId: number) => {
    selectPersona(userId);
    setOpen(false);
  };

  const handleLogout = async () => {
    setLoggingOut(true);
    setLogoutError(null);
    try {
      await logout();
      setOpen(false);
    } catch {
      setLogoutError("退出失败，请稍后重试");
    } finally {
      setLoggingOut(false);
    }
  };

  return (
    <div className="zr-account-menu" ref={rootRef}>
      <button
        ref={triggerRef}
        type="button"
        className="zr-account-menu__trigger"
        aria-expanded={open}
        aria-haspopup="menu"
        aria-controls="zr-account-menu-panel"
        aria-label={menuLabel}
        onClick={() => {
          setOpen((value) => !value);
          setLogoutError(null);
        }}
      >
        <span className="zr-account-menu__avatar" aria-hidden="true">
          {avatarText}
        </span>
        <span className="zr-account-menu__name">{user.display_name}</span>
        <ChevronDown
          className={`zr-account-menu__chevron${open ? " zr-account-menu__chevron--open" : ""}`}
          size={14}
          aria-hidden="true"
        />
      </button>

      {open && (
        <div
          id="zr-account-menu-panel"
          className="zr-account-menu__panel"
          role="menu"
          aria-label="账号与推荐画像"
        >
          <div className="zr-account-menu__identity">
            <span className="zr-account-menu__avatar zr-account-menu__avatar--large" aria-hidden="true">
              {avatarText}
            </span>
            <div className="zr-account-menu__identity-copy">
              <strong>{user.display_name}</strong>
              <span>{user.email}</span>
            </div>
          </div>

          <div className="zr-account-menu__section-label">推荐画像</div>
          <SlidingSelectionGroup
            activeIndex={loading ? -1 : selectedPersonaIndex}
            className="zr-account-menu__personas"
            indicatorTestId="account-persona-indicator"
            itemHeight={40}
            inset={6}
          >
            {loading && <div className="zr-account-menu__empty">正在加载画像…</div>}
            {!loading && personas.length === 0 && (
              <div className="zr-account-menu__empty">暂无可用画像</div>
            )}
            {!loading &&
              personas.map((persona) => {
                const active = persona.user_id === selectedPersona?.user_id;
                const label =
                  persona.user_id === user.user_id
                    ? "我的画像"
                    : localizePersonaName(persona.display_name);
                return (
                  <button
                    key={persona.user_id}
                    type="button"
                    role="menuitemradio"
                    aria-checked={active}
                    className={`zr-account-menu__persona${active ? " zr-account-menu__persona--active" : ""}`}
                    onClick={() => handleSelectPersona(persona.user_id)}
                  >
                    <span
                      className="zr-account-menu__persona-dot"
                      style={{ background: `hsl(${persona.user_id * 47 % 360} 58% 58%)` }}
                      aria-hidden="true"
                    />
                    <span>{label}</span>
                    {active && <span className="zr-account-menu__current">当前</span>}
                  </button>
                );
              })}
          </SlidingSelectionGroup>

          <div className="zr-account-menu__footer">
            <button
              type="button"
              className="zr-account-menu__logout"
              aria-label="退出登录"
              disabled={loggingOut}
              onClick={() => void handleLogout()}
            >
              <LogOut size={16} aria-hidden="true" />
              <span>{loggingOut ? "正在退出…" : "退出登录"}</span>
            </button>
            {logoutError && <div className="zr-account-menu__error">{logoutError}</div>}
          </div>
        </div>
      )}
    </div>
  );
}
