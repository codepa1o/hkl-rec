import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const globalStyles = readFileSync(resolve(process.cwd(), "src/styles/global.css"), "utf8");

describe("登录后页面背景", () => {
  it("使用项目内背景资源、固定铺满视口并提供明暗主题遮罩", () => {
    expect(
      existsSync(resolve(process.cwd(), "public/assets/cloud-night-background.png")),
    ).toBe(true);
    expect(globalStyles).toMatch(
      /\.zr-product-app\s*\{[^}]*url\("\/assets\/cloud-night-background\.png"\)[^}]*cover[^}]*fixed/s,
    );
    expect(globalStyles).toMatch(
      /:root\[data-theme="dark"\] \.zr-product-app\s*\{/,
    );
  });
});
