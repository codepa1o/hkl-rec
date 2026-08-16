import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { getArticleCard } from "../api/client";
import ArticleDetailPage from "./ArticleDetailPage";

vi.mock("../api/client", () => ({
  getArticleCard: vi.fn(),
  trackEvent: vi.fn().mockResolvedValue({ ok: true }),
}));

vi.mock("../context/PersonaContext", () => ({
  usePersona: () => ({ selectedPersona: null, bumpProfile: vi.fn() }),
}));

const article = {
  news_id: "N301",
  title: "A detailed article",
  abstract: "Article abstract",
  url: "https://example.com/N301",
  source_domain: "example.com",
  category: "news",
  subcategory: "world",
  categories: [{ topic_id: 1, display_name: "News" }],
  title_entities: [
    {
      label: "Ada Lovelace",
      entity_type: "person",
      type_code: "P",
      wikidata_id: "Q7259",
      confidence: 1,
      surface_forms: ["Ada"],
    },
    {
      label: "OpenAI",
      entity_type: "organization",
      type_code: "O",
      wikidata_id: "Q24283660",
      confidence: 0.91,
      surface_forms: ["OpenAI"],
    },
  ],
  abstract_entities: [
    {
      label: "Ada Lovelace",
      entity_type: "person",
      type_code: "P",
      wikidata_id: "Q7259",
      confidence: 0.8,
      surface_forms: ["Lovelace"],
    },
    {
      label: "London",
      entity_type: "location",
      type_code: "G",
      wikidata_id: "Q84",
      confidence: 0.95,
      surface_forms: ["London"],
    },
  ],
};

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/articles/N301"]}>
      <Routes>
        <Route path="/articles/:newsId" element={<ArticleDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("ArticleDetailPage entities", () => {
  beforeEach(() => {
    vi.mocked(getArticleCard).mockResolvedValue(article as never);
  });

  it("只在详情页按人物、机构和地点分组展示实体，并按 Wikidata ID 去重", async () => {
    renderPage();

    expect(await screen.findByRole("heading", { name: "相关实体" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "人物" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "机构" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "地点" })).toBeInTheDocument();
    expect(screen.getAllByText("Ada Lovelace")).toHaveLength(1);
    expect(screen.getByText("OpenAI")).toBeInTheDocument();
    expect(screen.getByText("London")).toBeInTheDocument();
  });

  it("没有实体时不渲染相关实体区域", async () => {
    vi.mocked(getArticleCard).mockResolvedValue({
      ...article,
      title_entities: [],
      abstract_entities: [],
    } as never);
    renderPage();

    expect(await screen.findByText("A detailed article")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "相关实体" })).not.toBeInTheDocument();
  });
});
