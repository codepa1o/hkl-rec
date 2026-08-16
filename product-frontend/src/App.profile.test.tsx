import type { ReactNode } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import App from "./App";

vi.mock("./context/AuthContext", () => ({
  AuthProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
}));
vi.mock("./context/ThemeContext", () => ({
  ThemeProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
}));
vi.mock("./context/PersonaContext", () => ({
  PersonaProvider: ({ children }: { children: ReactNode }) => <>{children}</>,
  usePersona: () => ({ refreshTick: 0, bumpProfile: vi.fn() }),
}));
vi.mock("./components/ProtectedRoute", () => ({
  default: ({ children }: { children: ReactNode }) => <>{children}</>,
}));
vi.mock("./components/TopNav", () => ({ default: () => <header>顶部导航</header> }));
vi.mock("./components/LeftSidebar", () => ({ default: () => <nav>左侧导航</nav> }));
vi.mock("./components/RightRail", () => ({
  default: () => <aside data-testid="right-rail">右侧栏</aside>,
}));
vi.mock("./components/ProfilePanel", () => ({
  default: ({ variant }: { variant?: string }) => (
    <section data-testid="profile-panel">{variant}</section>
  ),
}));
vi.mock("./pages/FeedPage", () => ({ default: () => <main>首页</main> }));
vi.mock("./pages/SearchPage", () => ({ default: () => <main>搜索页</main> }));
vi.mock("./pages/ArticleDetailPage", () => ({ default: () => <main>详情页</main> }));
vi.mock("./pages/AuthPage", () => ({ default: () => <main>登录页</main> }));

function LocationProbe() {
  return <output data-testid="location">{useLocation().pathname}</output>;
}

describe("独立兴趣画像路由", () => {
  it("保留左侧导航、隐藏右侧栏并渲染页面模式画像", async () => {
    render(
      <MemoryRouter initialEntries={["/profile"]}>
        <App />
        <LocationProbe />
      </MemoryRouter>,
    );

    await waitFor(() =>
      expect(screen.getByTestId("location")).toHaveTextContent("/profile"),
    );
    expect(screen.getByRole("heading", { name: "兴趣画像" })).toBeInTheDocument();
    expect(screen.getByTestId("profile-panel")).toHaveTextContent("page");
    expect(screen.queryByTestId("right-rail")).not.toBeInTheDocument();
  });
});
