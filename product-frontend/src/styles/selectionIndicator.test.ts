import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const globalStyles = readFileSync(resolve(process.cwd(), "src/styles/global.css"), "utf8");

function getRule(selector: string) {
  const escapedSelector = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return [...globalStyles.matchAll(new RegExp(`${escapedSelector}\\s*\\{([^}]*)\\}`, "g"))]
    .map((match) => match[1])
    .join("\n");
}

describe("共享选中框动画", () => {
  it("使用位移动画并服从系统的减少动态效果设置", () => {
    expect(getRule(".zr-selection-indicator")).toMatch(
      /transform:\s*translate3d\(0, var\(--zr-selection-offset\), 0\)/,
    );
    expect(getRule(".zr-selection-indicator")).toMatch(
      /transition:\s*transform 260ms cubic-bezier\(0\.22, 1, 0\.36, 1\)/,
    );
    expect(globalStyles).toMatch(
      /@media \(prefers-reduced-motion: reduce\)[\s\S]*transition-duration:\s*0\.01ms !important/,
    );
  });
});
