import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  getArticleCard,
  newClientId,
  sendTrackedEventKeepalive,
  trackEvent,
} from "../api/client";
import ArticleDetailPage from "./ArticleDetailPage";

const bumpProfile = vi.fn();

vi.mock("../context/PersonaContext", () => ({
  usePersona: () => ({
    selectedPersona: {
      user_id: 7004,
      display_name: "Reader",
      behavior_score: 0,
      top_topics: [],
    },
    bumpProfile,
  }),
}));

vi.mock("../api/client", () => ({
  getArticleCard: vi.fn(),
  newClientId: vi.fn(),
  sendTrackedEventKeepalive: vi.fn(),
  trackEvent: vi.fn(),
}));

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/articles/301"]}>
      <Routes>
        <Route path="/articles/:articleId" element={<ArticleDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ArticleDetailPage visible dwell", () => {
  let now = 0;

  beforeEach(() => {
    now = 0;
    vi.spyOn(performance, "now").mockImplementation(() => now);
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "visible",
    });
    vi.mocked(newClientId).mockReturnValue("route-load-1");
    vi.mocked(getArticleCard).mockResolvedValue({
      article_id: 301,
      headline: "A considered headline",
      abstract: "Article summary",
      source_domain: "news.example.com",
      categories: [],
    });
    vi.mocked(trackEvent).mockResolvedValue({
      ok: true,
      event_type: "detail_view",
      profile_updated: false,
      behavior_score: null,
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("pagehide 与卸载只提交一次达到阈值的可见停留", async () => {
    const rendered = renderPage();
    await screen.findByText("A considered headline");

    now = 12_400;
    window.dispatchEvent(new Event("pagehide"));

    expect(sendTrackedEventKeepalive).toHaveBeenCalledWith({
      event_id: "dwell-7004:301:route-load-1",
      user_id: 7004,
      event_type: "dwell",
      surface: "article_detail",
      article_id: 301,
      dwell_ms: 12_400,
    });
    rendered.unmount();
    expect(sendTrackedEventKeepalive).toHaveBeenCalledTimes(1);
  });

  it("隐藏期间暂停，累计不足十秒时不提交", async () => {
    const rendered = renderPage();
    await screen.findByText("A considered headline");

    now = 4_000;
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
    document.dispatchEvent(new Event("visibilitychange"));
    now = 40_000;
    rendered.unmount();

    expect(sendTrackedEventKeepalive).not.toHaveBeenCalled();
  });

  it("投递异常不阻塞页面卸载", async () => {
    vi.mocked(sendTrackedEventKeepalive).mockImplementationOnce(() => {
      throw new Error("delivery rejected");
    });
    renderPage();
    await screen.findByText("A considered headline");
    now = 11_000;

    expect(() => window.dispatchEvent(new Event("pagehide"))).not.toThrow();
    await waitFor(() => expect(screen.getByText("A considered headline")).toBeInTheDocument());
  });
});
