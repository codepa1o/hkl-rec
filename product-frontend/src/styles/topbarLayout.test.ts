import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const globalStyles = readFileSync(resolve(process.cwd(), "src/styles/global.css"), "utf8");

describe("顶部搜索框布局", () => {
  it("使用左右等宽列让桌面搜索框以视口为基准居中", () => {
    expect(globalStyles).toMatch(
      /\.zr-topbar\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\) minmax\(300px, 680px\) minmax\(0, 1fr\)/,
    );
    expect(globalStyles).toMatch(
      /@media \(max-width: 1160px\)[\s\S]*?\.zr-topbar\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\) minmax\(280px, 680px\) minmax\(0, 1fr\)/,
    );
  });
});
