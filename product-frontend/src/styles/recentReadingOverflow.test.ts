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

describe("最近阅读横向滚动", () => {
  it("将横向滚动限制在最近阅读列表内", () => {
    expect(globalStyles).toContain(".zr-right");
    expect(getRule(".zr-right")).toMatch(/overflow-x:\s*hidden/);
    expect(getRule(".zr-recent-list")).toMatch(/overflow-x:\s*auto/);
    expect(getRule(".zr-recent-row")).toMatch(/width:\s*max-content/);
    expect(getRule(".zr-recent-row")).toMatch(/min-width:\s*100%/);
  });

  it("将超出六行的记录限制在列表内部纵向滚动", () => {
    expect(getRule(".zr-recent-list")).toMatch(/max-height:\s*208px/);
    expect(getRule(".zr-recent-list")).toMatch(/overflow-y:\s*auto/);
  });
});
