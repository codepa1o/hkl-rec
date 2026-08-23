import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { listPersonas } from "../api/client";
import { PersonaProvider, usePersona } from "./PersonaContext";
import { readPersonaSelection, savePersonaSelection } from "../feed/feedSessionStore";

vi.mock("../api/client", () => ({ listPersonas: vi.fn() }));
const authState = vi.hoisted(() => ({
  user: { user_id: 1_000_000_000, email: "reader@example.com", display_name: "新闻读者" },
}));
vi.mock("./AuthContext", () => ({
  useAuth: () => authState,
}));
vi.mock("./SourceSpaceContext", () => ({
  useSourceSpace: () => ({ sourceSpace: "mind" }),
}));

function Probe() {
  const { selectedPersona, personas } = usePersona();
  return (
    <div>
      <span>当前：{selectedPersona?.user_id ?? "无"}</span>
      <span>账号：{personas[0]?.display_name ?? "无"}</span>
    </div>
  );
}

function SelectionProbe() {
  const { selectedPersona, selectPersona } = usePersona();
  return (
    <div>
      <span data-testid="selected-persona">{selectedPersona?.user_id ?? "none"}</span>
      <button type="button" onClick={() => selectPersona(7001)}>
        select-demo
      </button>
    </div>
  );
}

describe("PersonaProvider", () => {
  beforeEach(() => {
    authState.user = {
      user_id: 1_000_000_000,
      email: "reader@example.com",
      display_name: "新闻读者",
    };
    vi.mocked(listPersonas).mockResolvedValue({
      items: [
        { user_id: 7001, display_name: "演示用户", behavior_score: 3, top_topics: [] },
      ],
    });
  });

  it("切换登录账号后自动选择新账号画像", async () => {
    const view = render(
      <PersonaProvider>
        <Probe />
      </PersonaProvider>,
    );
    expect(await screen.findByText("当前：1000000000")).toBeInTheDocument();

    authState.user = {
      user_id: 1_000_000_001,
      email: "second@example.com",
      display_name: "第二位读者",
    };
    view.rerender(
      <PersonaProvider>
        <Probe />
      </PersonaProvider>,
    );

    expect(await screen.findByText("当前：1000000001")).toBeInTheDocument();
    expect(screen.getByText("账号：第二位读者")).toBeInTheDocument();
  });

  it("优先使用登录账号绑定的推荐画像，同时保留演示 persona", async () => {
    render(
      <PersonaProvider>
        <Probe />
      </PersonaProvider>,
    );

    expect(await screen.findByText("当前：1000000000")).toBeInTheDocument();
    expect(screen.getByText("账号：新闻读者")).toBeInTheDocument();
  });
});

describe("Persona session selection", () => {
  beforeEach(() => {
    sessionStorage.clear();
    authState.user = {
      user_id: 1_000_000_000,
      email: "reader@example.com",
      display_name: "Reader",
    };
    vi.mocked(listPersonas).mockResolvedValue({
      items: [
        { user_id: 7001, display_name: "Demo", behavior_score: 3, top_topics: [] },
      ],
    });
  });

  it("restores and persists the selected Persona for the account and source", async () => {
    savePersonaSelection(1_000_000_000, "mind", 7001);
    render(
      <PersonaProvider>
        <SelectionProbe />
      </PersonaProvider>,
    );

    expect(await screen.findByTestId("selected-persona")).toHaveTextContent("7001");
    fireEvent.click(screen.getByRole("button", { name: "select-demo" }));
    await waitFor(() =>
      expect(readPersonaSelection(1_000_000_000, "mind")).toBe(7001),
    );
  });

  it("ignores a stored Persona missing from the current source", async () => {
    savePersonaSelection(1_000_000_000, "mind", 9999);
    render(
      <PersonaProvider>
        <SelectionProbe />
      </PersonaProvider>,
    );

    expect(await screen.findByTestId("selected-persona")).toHaveTextContent("1000000000");
  });
});
