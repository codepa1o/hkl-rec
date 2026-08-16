import { CircleUserRound, FlaskConical, Home, Search } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { listCategories } from "../api/client";
import type { CategoryItem } from "../api/types";
import { localizeCategoryName } from "../localization";
import SlidingSelectionGroup from "./SlidingSelectionGroup";

function navClass({ isActive }: { isActive: boolean }) {
  return `zr-left__item${isActive ? " zr-left__item--active" : ""}`;
}

export default function LeftSidebar() {
  const location = useLocation();
  const selectedCategory = new URLSearchParams(location.search).get("category");
  const [categories, setCategories] = useState<CategoryItem[]>([]);
  const [categoryError, setCategoryError] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);
  const matchedCategoryIndex = categories.findIndex(
    (category) => category.key === selectedCategory,
  );
  const isFeedPath = location.pathname === "/";
  const categoryActiveIndex =
    !isFeedPath
      ? -1
      : selectedCategory === null
        ? 0
        : matchedCategoryIndex >= 0
          ? matchedCategoryIndex + 1
          : -1;
  const primaryActiveIndex =
    location.pathname === "/search"
      ? 1
      : location.pathname === "/profile"
        ? 2
        : location.pathname === "/"
          ? 0
          : -1;

  const reloadCategories = useCallback(() => {
    setReloadToken((current) => current + 1);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setCategoryError(false);
    void listCategories()
      .then((response) => {
        if (!cancelled) setCategories(response.items);
      })
      .catch(() => {
        if (!cancelled) setCategoryError(true);
      });
    return () => {
      cancelled = true;
    };
  }, [reloadToken]);

  return (
    <nav className="zr-left" aria-label="主导航">
      <SlidingSelectionGroup
        activeIndex={primaryActiveIndex}
        className="zr-left__section zr-left__section--primary"
        indicatorTestId="primary-navigation-indicator"
        itemHeight={44}
        itemStep={49}
      >
        <NavLink to="/" end className={navClass}>
          <Home size={19} />
          <span>首页</span>
        </NavLink>
        <NavLink to="/search" className={navClass}>
          <Search size={19} />
          <span>搜索</span>
        </NavLink>
        <NavLink to="/profile" className={navClass}>
          <CircleUserRound size={19} />
          <span>兴趣画像</span>
        </NavLink>
      </SlidingSelectionGroup>

      <div className="zr-left__section zr-left__section--categories">
        <div className="zr-left__section-title">新闻分类</div>
        <SlidingSelectionGroup
          activeIndex={categoryActiveIndex}
          className="zr-left__category-list"
          indicatorTestId="news-category-indicator"
          itemHeight={44}
        >
          <Link
            to="/"
            className={`zr-left__item${isFeedPath && selectedCategory === null ? " zr-left__item--active" : ""}`}
            aria-current={isFeedPath && selectedCategory === null ? "page" : undefined}
          >
            <span className="zr-category-dot" aria-hidden="true" />
            <span>全部新闻</span>
          </Link>
          {categories.map((category) => (
            <Link
              key={category.key}
              data-testid="news-category-link"
              to={`/?category=${encodeURIComponent(category.key)}`}
              className={`zr-left__item${isFeedPath && selectedCategory === category.key ? " zr-left__item--active" : ""}`}
              aria-current={
                isFeedPath && selectedCategory === category.key ? "page" : undefined
              }
            >
              <span className="zr-category-dot" aria-hidden="true" />
              <span>{localizeCategoryName(category.key)}</span>
            </Link>
          ))}
          {categoryError && (
            <div className="zr-left__category-error" role="alert">
              <span>分类加载失败</span>
              <button type="button" onClick={reloadCategories}>
                重新加载
              </button>
            </div>
          )}
        </SlidingSelectionGroup>
      </div>

      <div className="zr-left__footer">
        <FlaskConical size={16} />
        <span>由个性化推荐模型驱动</span>
      </div>
    </nav>
  );
}
