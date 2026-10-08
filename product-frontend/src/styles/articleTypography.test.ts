import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const globalStyles = readFileSync(resolve(process.cwd(), "src/styles/global.css"), "utf8");
const liveNewsStyles = readFileSync(resolve(process.cwd(), "src/styles/liveNews.css"), "utf8");

describe("文章详情阅读字号", () => {
  it("来源信息独立排版、不继承首行缩进，并支持窄屏换行", () => {
    const metadata = liveNewsStyles.match(/\.zr-article-metadata\s*\{([^}]+)\}/)?.[1] ?? "";
    expect(metadata).toMatch(/text-indent:\s*0/);
    expect(metadata).toMatch(/font-size:\s*0\.8125rem/);
    expect(metadata).toMatch(/line-height:\s*1\.6/);
    const details = liveNewsStyles.match(/\.zr-article-metadata__details\s*\{([^}]+)\}/)?.[1] ?? "";
    expect(details).toMatch(/flex-wrap:\s*wrap/);
    expect(liveNewsStyles).toMatch(/\.zr-article-metadata__item dd\s*\{[^}]*margin:\s*0/);
  });
  it("放大栏目标题、摘要和正文，并只缩进普通正文段落", () => {
    expect(globalStyles).toMatch(
      /\.zr-post-detail__content\s*>\s*\.zr-eyebrow[\s\S]*?font-size:\s*14px/,
    );
    expect(globalStyles).toMatch(
      /\.zr-post-detail__summary[\s\S]*?font-size:\s*18px/,
    );
    expect(liveNewsStyles).toMatch(
      /\.zr-post-detail__body-copy[\s\S]*?font-size:\s*clamp\(1\.125rem,[^;]+1\.25rem\)/,
    );
    expect(liveNewsStyles).toMatch(
      /\.zr-structured-article-body[\s\S]*?font-size:\s*clamp\(1\.125rem,[^;]+1\.25rem\)/,
    );
    expect(liveNewsStyles).toMatch(
      /\.zr-post-detail__body-copy p[\s\S]*?text-indent:\s*2em/,
    );
    expect(liveNewsStyles).toMatch(
      /\.zr-structured-article-body\s*>\s*p[\s\S]*?text-indent:\s*2em/,
    );
  });
});
