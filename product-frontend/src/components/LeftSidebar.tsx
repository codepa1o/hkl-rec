import { CircleUserRound, FlaskConical, Home, Search } from "lucide-react";
import { NavLink } from "react-router-dom";

const categories = [
  { label: "体育", query: "sports" },
  { label: "财经", query: "finance" },
  { label: "科学", query: "science" },
];

function navClass({ isActive }: { isActive: boolean }) {
  return `zr-left__item${isActive ? " zr-left__item--active" : ""}`;
}

export default function LeftSidebar() {
  return (
    <nav className="zr-left" aria-label="主导航">
      <div className="zr-left__section zr-left__section--primary">
        <NavLink to="/" end className={navClass}>
          <Home size={19} />
          <span>首页</span>
        </NavLink>
        <NavLink to="/search" className={navClass}>
          <Search size={19} />
          <span>搜索</span>
        </NavLink>
        <a href="#your-interests" className="zr-left__item">
          <CircleUserRound size={19} />
          <span>兴趣画像</span>
        </a>
      </div>

      <div className="zr-left__section zr-left__section--categories">
        <div className="zr-left__section-title">新闻分类</div>
        {categories.map((category) => (
          <NavLink
            key={category.query}
            to={`/search?q=${category.query}`}
            className="zr-left__item"
          >
            <span className="zr-category-dot" aria-hidden="true" />
            <span>{category.label}</span>
          </NavLink>
        ))}
      </div>

      <div className="zr-left__footer">
        <FlaskConical size={16} />
        <span>由个性化推荐模型驱动</span>
      </div>
    </nav>
  );
}
