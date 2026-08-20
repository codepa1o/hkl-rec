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

  it("隐藏浏览器原生密码眼睛以免与自定义按钮重复", () => {
    const nativeRevealRule = getRule(".zr-auth-password input::-ms-reveal");

    expect(nativeRevealRule).toMatch(/display:\s*none/);
  });

  it("浅色认证页使用暖纸日光配色", () => {
    const lightThemeRule = getRule(':root[data-theme="light"] .zr-auth-page');

    expect(lightThemeRule).toMatch(/--zr-auth-page-bg:\s*#f8f4ea/);
    expect(lightThemeRule).toMatch(/--zr-auth-story-bg:\s*#eee7d8/);
    expect(lightThemeRule).toMatch(/--zr-accent:\s*#6f4bd8/);
    expect(lightThemeRule).toMatch(/--zr-auth-submit-hover:\s*#7655dc/);
    expect(lightThemeRule).toMatch(/--zr-text-faint:\s*#746a60/);
    expect(lightThemeRule).toMatch(/--zr-auth-story-note:\s*rgba\(33, 28, 40, 0\.65\)/);
    expect(lightThemeRule).toMatch(/color-scheme:\s*light/);
  });

  it("将认证页主题按钮固定在表单区右上角", () => {
    const themeToggleRule = getRule(".zr-auth-theme-toggle");

    expect(themeToggleRule).toMatch(/position:\s*absolute/);
    expect(themeToggleRule).toMatch(/top:\s*clamp\(/);
    expect(themeToggleRule).toMatch(/right:\s*clamp\(/);
  });

  it("减少动效时隐藏噪点并移除认证内容的位移与模糊", () => {
    expect(getRule(".zr-auth-grain")).toMatch(/display:\s*none/);
    expect(getRule(".zr-auth-story__copy")).toMatch(/transform:\s*none\s*!important/);
    expect(getRule(".zr-auth-form-wrap")).toMatch(/filter:\s*none\s*!important/);
  });
});
