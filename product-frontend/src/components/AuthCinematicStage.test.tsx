import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ThemeProvider } from "../context/ThemeContext";
import AuthCinematicStage from "./AuthCinematicStage";

function renderWithTheme(stage: ReactElement) {
  return render(<ThemeProvider>{stage}</ThemeProvider>);
}

describe("AuthCinematicStage", () => {
  beforeEach(() => {
    localStorage.clear();
    Object.defineProperty(window, "matchMedia", {
      configurable: true,
      value: vi.fn().mockReturnValue({ matches: true }),
    });
  });

  afterEach(() => {
    document.documentElement.removeAttribute("data-theme");
  });

  it("renders the login story and exposes the active phase", () => {
    renderWithTheme(
      <AuthCinematicStage mode="login" phase="idle" reducedMotion={false}>
        <span>表单内容</span>
      </AuthCinematicStage>,
    );

    const stage = screen.getByTestId("auth-stage");
    expect(stage).toHaveAttribute("data-phase", "idle");
    expect(stage).toHaveAttribute("data-mode", "login");
    expect(screen.getByRole("heading", { name: "继续你的阅读脉络" })).toBeInTheDocument();
    expect(screen.getByText("表单内容")).toBeInTheDocument();
    expect(document.querySelectorAll(".zr-auth-curtain")).toHaveLength(2);
    expect(document.querySelector(".zr-auth-grain")).toHaveAttribute("aria-hidden", "true");
    expect(stage.querySelector(".zr-auth-panel")).toBeInTheDocument();
  });

  it("renders the registration story and success status", () => {
    renderWithTheme(
      <AuthCinematicStage mode="register" phase="success" reducedMotion>
        <span>注册表单</span>
      </AuthCinematicStage>,
    );

    expect(screen.getByRole("heading", { name: "建立你的阅读坐标" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("阅读世界正在展开");
  });

  it("在表单区提供同步全站状态的主题切换按钮", () => {
    renderWithTheme(
      <AuthCinematicStage mode="login" phase="idle" reducedMotion>
        <span>登录表单</span>
      </AuthCinematicStage>,
    );

    const toggle = screen.getByRole("button", { name: "切换为浅色主题" });
    expect(toggle).toHaveClass("zr-auth-theme-toggle");

    fireEvent.click(toggle);

    expect(screen.getByRole("button", { name: "切换为深色主题" })).toBeInTheDocument();
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(localStorage.getItem("news-intent-theme")).toBe("light");
  });

  it("fades the outgoing scene before the curtain swaps to incoming content", () => {
    const view = renderWithTheme(
      <AuthCinematicStage mode="login" phase="idle" reducedMotion={false}>
        <form aria-label="认证表单" />
      </AuthCinematicStage>,
    );

    view.rerender(
      <ThemeProvider>
        <AuthCinematicStage mode="login" phase="switching" reducedMotion={false}>
          <form aria-label="认证表单" />
        </AuthCinematicStage>
      </ThemeProvider>,
    );
    expect(view.container.querySelector(".zr-auth-story__copy")).toHaveAttribute(
      "data-scene-state",
      "exiting",
    );
    expect(view.container.querySelector(".zr-auth-form-wrap")).toHaveAttribute(
      "data-scene-state",
      "exiting",
    );

    view.rerender(
      <ThemeProvider>
        <AuthCinematicStage mode="register" phase="switching" reducedMotion={false}>
          <form aria-label="认证表单" />
        </AuthCinematicStage>
      </ThemeProvider>,
    );
    expect(screen.getByRole("heading", { name: "建立你的阅读坐标" })).toBeInTheDocument();
    expect(view.container.querySelector(".zr-auth-story__copy")).toHaveAttribute(
      "data-scene-state",
      "entering",
    );
    expect(view.container.querySelector(".zr-auth-form-wrap")).toHaveAttribute(
      "data-scene-state",
      "entering",
    );
  });
});
