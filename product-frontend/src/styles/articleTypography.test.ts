import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const globalStyles = readFileSync(resolve(process.cwd(), "src/styles/global.css"), "utf8");
const liveNewsStyles = readFileSync(resolve(process.cwd(), "src/styles/liveNews.css"), "utf8");

describe("文章详情阅读字号", () => {
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
