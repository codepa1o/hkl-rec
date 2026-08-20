import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { listNewsSpaces } from "../api/client";
import { SourceSpaceProvider, useSourceSpace } from "./SourceSpaceContext";

vi.mock("../api/client", () => ({ listNewsSpaces: vi.fn() }));

function Probe() {
  const { sourceSpace, liveEnabled, selectSourceSpace } = useSourceSpace();
  return (
    <div>
      <span data-testid="space">{sourceSpace}</span>
      <span data-testid="live-enabled">{String(liveEnabled)}</span>
      <button type="button" onClick={() => selectSourceSpace("live")}>
        实时新闻
      </button>
    </div>
  );
}

describe("SourceSpaceProvider", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.mocked(listNewsSpaces).mockResolvedValue({
      items: [
        { source_space: "mind", enabled: true },
        { source_space: "live", enabled: true },
      ],
    });
  });

  it("defaults to mind and persists a live selection", async () => {
    render(
      <SourceSpaceProvider>
        <Probe />
      </SourceSpaceProvider>,
    );
    await waitFor(() => expect(screen.getByTestId("live-enabled")).toHaveTextContent("true"));

    fireEvent.click(screen.getByRole("button", { name: "实时新闻" }));

    expect(screen.getByTestId("space")).toHaveTextContent("live");
    expect(localStorage.getItem("newsrec:source-space")).toBe("live");
  });

  it("falls back to mind when a persisted live space is disabled", async () => {
    localStorage.setItem("newsrec:source-space", "live");
    vi.mocked(listNewsSpaces).mockResolvedValue({
      items: [
        { source_space: "mind", enabled: true },
        { source_space: "live", enabled: false },
      ],
    });

    render(
      <SourceSpaceProvider>
        <Probe />
      </SourceSpaceProvider>,
    );

    await waitFor(() => expect(screen.getByTestId("space")).toHaveTextContent("mind"));
    expect(localStorage.getItem("newsrec:source-space")).toBe("mind");
  });
});
