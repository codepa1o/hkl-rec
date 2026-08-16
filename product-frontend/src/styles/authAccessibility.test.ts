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

describe("认证页无障碍动效样式", () => {
  it("为键盘聚焦的输入框提供明确焦点环", () => {
    const focusVisibleRule = getRule(".zr-auth-field input:focus-visible");

    expect(focusVisibleRule).toMatch(/outline:\s*3px solid/);
    expect(focusVisibleRule).toMatch(/outline-offset:\s*3px/);
  });

  it("减少动效时隐藏噪点并移除认证内容的位移与模糊", () => {
    expect(getRule(".zr-auth-grain")).toMatch(/display:\s*none/);
    expect(getRule(".zr-auth-story__copy")).toMatch(/transform:\s*none\s*!important/);
    expect(getRule(".zr-auth-form-wrap")).toMatch(/filter:\s*none\s*!important/);
  });
});
