import { describe, expect, it } from "vitest";
import { VisibleDwellAccumulator, dwellEventId } from "./visibleDwell";

describe("VisibleDwellAccumulator", () => {
  it("只累计可见时间并在隐藏期间暂停", () => {
    let now = 0;
    const dwell = new VisibleDwellAccumulator(() => now, true);

    now = 4_000;
    dwell.setVisible(false);
    now = 104_000;
    expect(dwell.elapsedMs()).toBe(4_000);

    dwell.setVisible(true);
    now = 111_500;
    expect(dwell.elapsedMs()).toBe(11_500);
  });

  it("低于阈值不发送，达到阈值后至多取值一次", () => {
    let now = 0;
    const dwell = new VisibleDwellAccumulator(() => now, true);

    now = 9_999;
    expect(dwell.takeForSend(10_000)).toBeNull();
    now = 10_500;
    expect(dwell.takeForSend(10_000)).toBe(10_500);
    now = 20_000;
    expect(dwell.takeForSend(10_000)).toBeNull();
  });

  it("同一路由加载生成稳定且可判重的事件 ID", () => {
    expect(dwellEventId(7004, 301, "route-load-1")).toBe(
      "dwell-7004:301:route-load-1",
    );
    expect(dwellEventId(7004, 301, "route-load-1")).toBe(
      dwellEventId(7004, 301, "route-load-1"),
    );
  });
});
