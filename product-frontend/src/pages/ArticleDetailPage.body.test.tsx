import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import {
  getArticleCard,
  newClientId,
  sendTrackedEventKeepalive,
  trackEvent,
} from "../api/client";
import type { ArticleCardResponse } from "../api/types";
import ArticleDetailPage from "./ArticleDetailPage";

vi.mock("../context/PersonaContext", () => ({
  usePersona: () => ({
    selectedPersona: {
      user_id: 7004,
      display_name: "Reader",
      behavior_score: 0,
      top_topics: [],
    },
    bumpProfile: vi.fn(),
  }),
}));

vi.mock("../api/client", () => ({
  getArticleCard: vi.fn(),
  newClientId: vi.fn(),
  sendTrackedEventKeepalive: vi.fn(),
  trackEvent: vi.fn(),
}));

const baseArticle: ArticleCardResponse = {
  source_space: "live",
  article_id: "L0123456789abcdef0123456789abcdef",
  title: "Live article with body",
  abstract: "Stored metadata description",
  url: "https://example.com/story",
  source_domain: "example.com",
  category: "",
  subcategory: "",
  categories: [],
  title_entities: [],
  abstract_entities: [],
  body_text: null,
  body_status: "metadata_only",
  body_source: null,
  content_rights: "link_only",
};

function renderPage(article: ArticleCardResponse) {
  vi.mocked(getArticleCard).mockResolvedValue(article);
  return render(
    <MemoryRouter initialEntries={[`/articles/live/${article.article_id}`]}>
      <Routes>
        <Route path="/articles/:sourceSpace/:articleId" element={<ArticleDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(newClientId).mockReturnValue("route-load-1");
  vi.mocked(trackEvent).mockResolvedValue({
    ok: true,
    event_type: "detail_view",
    source_space: "live",
    profile_updated: false,
    behavior_score: null,
  });
  vi.mocked(sendTrackedEventKeepalive).mockImplementation(() => undefined);
});

it("renders available body as separate text paragraphs", async () => {
  renderPage({
    ...baseArticle,
    body_text: "First published paragraph.\n\nSecond published paragraph.",
    body_status: "available",
    body_source: "html",
    content_rights: "full_text",
  });

  expect(await screen.findByText("First published paragraph.")).toBeInTheDocument();
  expect(screen.getByText("Second published paragraph.")).toBeInTheDocument();
  expect(screen.getByText("正文")).toBeInTheDocument();
});

it("renders provider markup as text instead of executable HTML", async () => {
  renderPage({
    ...baseArticle,
    body_text: '<script data-provider="unsafe">alert("x")</script>',
    body_status: "available",
    body_source: "html",
    content_rights: "full_text",
  });

  expect(
    await screen.findByText('<script data-provider="unsafe">alert("x")</script>'),
  ).toBeInTheDocument();
  expect(document.querySelector("script[data-provider='unsafe']")).toBeNull();
});

it("keeps summary and original link when body acquisition failed", async () => {
  renderPage({
    ...baseArticle,
    body_status: "failed",
    content_rights: "full_text",
  });

  expect(await screen.findByText("Stored metadata description")).toBeInTheDocument();
  expect(screen.getByRole("link", { name: "阅读原文" })).toHaveAttribute(
    "href",
    baseArticle.url,
  );
});

it("shows a neutral pending message without hiding the summary", async () => {
  renderPage({
    ...baseArticle,
    body_status: "pending",
    content_rights: "full_text",
  });

  expect(await screen.findByText("正文正在获取中…")).toBeInTheDocument();
  expect(screen.getByText("Stored metadata description")).toBeInTheDocument();
});
