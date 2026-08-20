import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import SourceSpaceSwitcher from "./SourceSpaceSwitcher";

const state = vi.hoisted(() => ({
  sourceSpace: "mind" as "mind" | "live",
  liveEnabled: true,
  selectSourceSpace: vi.fn(),
}));

vi.mock("../context/SourceSpaceContext", () => ({ useSourceSpace: () => state }));

it("switches between MIND and Live with an accessible segmented control", () => {
  render(<SourceSpaceSwitcher />);

  expect(screen.getByRole("button", { name: "MIND 数据集" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  fireEvent.click(screen.getByRole("button", { name: "实时新闻" }));
  expect(state.selectSourceSpace).toHaveBeenCalledWith("live");
});
