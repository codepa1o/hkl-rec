import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import AuthCinematicStage from "./AuthCinematicStage";

describe("AuthCinematicStage", () => {
  it("renders the login story and exposes the active phase", () => {
    render(
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
    render(
      <AuthCinematicStage mode="register" phase="success" reducedMotion>
        <span>注册表单</span>
      </AuthCinematicStage>,
    );

    expect(screen.getByRole("heading", { name: "建立你的阅读坐标" })).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("阅读世界正在展开");
  });

  it("fades the outgoing scene before the curtain swaps to incoming content", () => {
    const view = render(
      <AuthCinematicStage mode="login" phase="idle" reducedMotion={false}>
        <form aria-label="认证表单" />
      </AuthCinematicStage>,
    );

    view.rerender(
      <AuthCinematicStage mode="login" phase="switching" reducedMotion={false}>
        <form aria-label="认证表单" />
      </AuthCinematicStage>,
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
      <AuthCinematicStage mode="register" phase="switching" reducedMotion={false}>
        <form aria-label="认证表单" />
      </AuthCinematicStage>,
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
