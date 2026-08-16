import { afterEach, describe, expect, it, vi } from "vitest";
import { sendTrackedEventKeepalive } from "./client";

const payload = {
  event_id: "dwell-7004:301:route-load-1",
  user_id: 7004,
  event_type: "dwell" as const,
  surface: "article_detail",
  article_id: 301,
  dwell_ms: 12_000,
};

describe("sendTrackedEventKeepalive", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("优先使用 sendBeacon", () => {
    const beacon = vi.fn(() => true);
    const fetchMock = vi.fn();
    Object.defineProperty(navigator, "sendBeacon", {
      configurable: true,
      value: beacon,
    });
    vi.stubGlobal("fetch", fetchMock);

    sendTrackedEventKeepalive(payload);

    expect(beacon).toHaveBeenCalledWith(
      expect.stringMatching(/\/event\/track\/beacon$/),
      JSON.stringify(payload),
    );
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("beacon 拒绝后使用 keepalive fetch，并吞掉异步失败", async () => {
    Object.defineProperty(navigator, "sendBeacon", {
      configurable: true,
      value: vi.fn(() => false),
    });
    const fetchMock = vi.fn().mockRejectedValue(new Error("network closed"));
    vi.stubGlobal("fetch", fetchMock);

    expect(() => sendTrackedEventKeepalive(payload)).not.toThrow();
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringMatching(/\/event\/track$/),
      expect.objectContaining({ method: "POST", keepalive: true, credentials: "include" }),
    );
    await Promise.resolve();
  });
});
