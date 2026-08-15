import { LogOut, Moon, Sun } from "lucide-react";
import { Link } from "react-router-dom";
import { useTheme } from "../context/ThemeContext";
import { useAuth } from "../context/AuthContext";
import PersonaSwitcher from "./PersonaSwitcher";
import SearchBox from "./SearchBox";

export default function TopNav() {
  const { resolvedTheme, toggleTheme } = useTheme();
  const { user, logout } = useAuth();
  const isDark = resolvedTheme === "dark";
  const handleLogout = () => {
    void logout().catch(() => undefined);
  };

  return (
    <header className="zr-topbar">
      <Link to="/" className="zr-topbar__brand" aria-label="新闻意图推荐首页">
        <span className="zr-topbar__mark">N</span>
        <span>新闻意图推荐</span>
      </Link>

      <div className="zr-topbar__search">
        <SearchBox />
      </div>

      <div className="zr-topbar__actions">
        <button
          type="button"
          className="zr-icon-button"
          aria-label={isDark ? "切换为浅色主题" : "切换为深色主题"}
          title={isDark ? "切换为浅色主题" : "切换为深色主题"}
          onClick={toggleTheme}
        >
          {isDark ? <Sun size={18} /> : <Moon size={18} />}
        </button>
        <span className="zr-account" title={user?.email}>
          {user?.display_name}
        </span>
        <button
          type="button"
          className="zr-icon-button"
          aria-label="退出登录"
          title="退出登录"
          onClick={handleLogout}
        >
          <LogOut size={18} />
        </button>
        <PersonaSwitcher />
      </div>
    </header>
  );
}
