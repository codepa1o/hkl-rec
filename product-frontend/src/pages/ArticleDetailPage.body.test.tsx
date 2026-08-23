import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, expect, it, vi } from "vitest";
import {
  ensureArticleContent,
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

vi.mock("../context/SourceSpaceContext", () => ({
  useSourceSpace: () => ({ selectSourceSpace: vi.fn() }),
}));

vi.mock("../api/client", () => ({
  ensureArticleContent: vi.fn(),
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
  vi.mocked(ensureArticleContent).mockResolvedValue({
    article_id: baseArticle.article_id,
    status: "pending",
    enqueued: true,
    retry_after_seconds: 5,
  });
});

it("renders structured paragraphs and inline images in document order", async () => {
  renderPage({
    ...baseArticle,
    body_text: "First paragraph.\n\nCaption\n\nSecond paragraph.",
    body_status: "available",
    body_source: "guardian_api",
    content_rights: "full_text",
    body_structure_status: "available",
    body_document_version: "structured-1",
    body_document: {
      schema_version: 1,
      extraction_version: "structured-1",
      source: "guardian_api",
      blocks: [
        { id: "p-1", type: "paragraph", text: "First paragraph." },
        {
          id: "img-2",
          type: "image",
          asset_id: "asset-2",
          source_url: "https://i.guim.co.uk/photo.jpg",
          display_url: "https://i.guim.co.uk/photo.jpg",
          alt: "Trading floor",
          caption: "Caption",
          credit: "Photograph: Example",
          width: 1200,
          height: 800,
          mime_type: "image/jpeg",
          cache_status: "remote_only",
        },
        { id: "p-3", type: "paragraph", text: "Second paragraph." },
      ],
    },
  });

  const first = await screen.findByText("First paragraph.");
  const image = screen.getByRole("img", { name: "Trading floor" });
  const second = screen.getByText("Second paragraph.");
  expect(first.compareDocumentPosition(image) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(image.compareDocumentPosition(second) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
});

it("requests asynchronous structure while keeping existing text readable", async () => {
  renderPage({
    ...baseArticle,
    body_text: "Readable fallback paragraph.",
    body_status: "available",
    body_source: "guardian_api",
    content_rights: "full_text",
    body_structure_status: "missing",
  });

  expect(await screen.findByText("Readable fallback paragraph.")).toBeInTheDocument();
  expect(await screen.findByText("正在优化图文排版")).toBeInTheDocument();
  expect(ensureArticleContent).toHaveBeenCalledWith("live", baseArticle.article_id);
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
