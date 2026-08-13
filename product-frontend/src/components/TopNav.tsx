import { Moon, Sun } from "lucide-react";
import { Link } from "react-router-dom";
import { useTheme } from "../context/ThemeContext";
import PersonaSwitcher from "./PersonaSwitcher";
import SearchBox from "./SearchBox";

export default function TopNav() {
  const { resolvedTheme, toggleTheme } = useTheme();
  const isDark = resolvedTheme === "dark";

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
        <PersonaSwitcher />
      </div>
    </header>
  );
}
