import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ProtectedRoute from "./ProtectedRoute";

const authState = { user: null as null | { user_id: number }, loading: false };
vi.mock("../context/AuthContext", () => ({ useAuth: () => authState }));

function renderRoute() {
  return render(
    <MemoryRouter initialEntries={["/private"]}>
      <Routes>
        <Route path="/auth" element={<span>登录页面</span>} />
        <Route
          path="/private"
          element={
            <ProtectedRoute>
              <span>受保护内容</span>
            </ProtectedRoute>
          }
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ProtectedRoute", () => {
  beforeEach(() => {
    authState.user = null;
    authState.loading = false;
  });

  it("未登录时跳转登录页", () => {
    renderRoute();
    expect(screen.getByText("登录页面")).toBeInTheDocument();
    expect(screen.queryByText("受保护内容")).not.toBeInTheDocument();
  });

  it("已登录时呈现受保护内容", () => {
    authState.user = { user_id: 7004 };
    renderRoute();
    expect(screen.getByText("受保护内容")).toBeInTheDocument();
  });

  it("恢复会话期间不提前跳转", () => {
    authState.loading = true;
    renderRoute();
    expect(screen.getByText("正在恢复阅读进度…")).toBeInTheDocument();
    expect(screen.queryByText("登录页面")).not.toBeInTheDocument();
  });
});
