import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { StructuredBodyDocument } from "../api/types";
import StructuredArticleBody from "./StructuredArticleBody";

const document: StructuredBodyDocument = {
  schema_version: 1,
  extraction_version: "structured-1",
  source: "guardian_api",
  blocks: [
    { id: "p-1", type: "paragraph", text: "First paragraph." },
    { id: "h-2", type: "heading", level: 2, text: "Inside the building" },
    { id: "q-3", type: "quote", text: "A radical building.", attribution: "Architect" },
    {
      id: "img-4",
      type: "image",
      asset_id: "asset-4",
      source_url: "https://i.guim.co.uk/floor.jpg",
      display_url: "https://i.guim.co.uk/floor.jpg",
      alt: "Trading floor",
      caption: "The main trading floor",
      credit: "Photograph: Example",
      width: 1200,
      height: 800,
      mime_type: "image/jpeg",
      cache_status: "remote_only",
    },
    { id: "l-5", type: "list", ordered: true, items: ["First", "Second"] },
    { id: "p-6", type: "paragraph", text: "Final paragraph." },
  ],
};

describe("StructuredArticleBody", () => {
  it("groups source, author and publication time outside prose paragraphs", () => {
    render(<StructuredArticleBody document={{...document, source: "html", byline: "Associated Press",
      published_at: "2026-09-16T01:28:20Z", fallback_reason: "api_tier_restricted"}} />);
    const metadata = screen.getByRole("group", {name: "正文来源信息"});
    expect(within(metadata).getByText("原站网页")).toBeInTheDocument();
    expect(within(metadata).getByText("Associated Press").closest("dd")).not.toBeNull();
    expect(metadata.querySelector("time")).toHaveAttribute("datetime", "2026-09-16T01:28:20Z");
    expect(metadata.querySelector("time")).not.toHaveTextContent(/:20$/);
    expect(metadata.querySelector("p")).toBeNull();
    expect(metadata.closest("[data-content-block-id]")).toBeNull();
    expect(screen.getByText("First paragraph.").tagName).toBe("P");
  });

  it("omits empty metadata rows and invalid dates", () => {
    render(<StructuredArticleBody document={{...document, source: "html", published_at: "invalid-date"}} />);
    const metadata = screen.getByRole("group", {name: "正文来源信息"});
    expect(within(metadata).getByText("原站网页")).toBeInTheDocument();
    expect(metadata.querySelector("time")).toBeNull();
    expect(within(metadata).queryByText("作者")).not.toBeInTheDocument();
  });
  it("resolves research image paths against the backend and retains the caption", () => {
    const path = `/articles/live/L${"1".repeat(32)}/assets/${"a".repeat(32)}`;
    const image = document.blocks[3];
    if (image.type !== "image") throw new Error("invalid fixture");
    render(<StructuredArticleBody document={{...document, blocks: [{...image,
      source_url: "http://www.fj.xinhuanet.com/a.png", display_url: path,
    }]}} />);
    const img = screen.getByRole("img", {name: "Trading floor"});
    expect(img.getAttribute("src")).toMatch(new RegExp(`:8000${path}$`));
    expect(screen.getAllByText("The main trading floor")).toHaveLength(1);
  });
  it("never falls back to a raw HTTP publisher image", () => {
    const image = document.blocks[3];
    if (image.type !== "image") throw new Error("invalid fixture");
    render(<StructuredArticleBody document={{...document, blocks: [{...image,
      source_url: "http://www.fj.xinhuanet.com/a.png", display_url: null,
    }]}} />);
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByText("图片暂时无法加载")).toBeInTheDocument();
    expect(screen.getByText("The main trading floor")).toBeInTheDocument();
  });
  it("shows HTML source warnings and publisher byline outside body blocks", () => {
    render(<StructuredArticleBody document={{...document, source: "html", byline: "Reuters", warnings: ["原文包含视频，请阅读原文查看。"]}} />);
    expect(within(screen.getByRole("group", {name: "正文来源信息"})).getByText("Reuters")).toBeInTheDocument();
    expect(screen.getByText("原文包含视频，请阅读原文查看。")).toBeInTheDocument();
  });
  it("renders publisher topics separately as safe chips and keeps real body lists", () => {
    const { container } = render(<StructuredArticleBody document={{...document, publisher_tags: [
      {name: "Public affairs", url: "https://www.theguardian.com/world/public-affairs"},
      {name: "Unsafe", url: "javascript:alert(1)"},
    ]}} />);
    const tag = screen.getByRole("link", {name: "Public affairs"});
    expect(tag).toHaveClass("zr-publisher-tag");
    expect(tag).toHaveAttribute("rel", "noopener noreferrer");
    expect(tag.closest("[data-content-block-id]")).toBeNull();
    expect(screen.getByRole("list").tagName).toBe("OL");
    expect(screen.queryByRole("link", {name: "Unsafe"})).not.toBeInTheDocument();
    expect(container.querySelectorAll(".zr-publisher-tags")).toHaveLength(1);
  });
  it("renders semantic blocks in publisher order", () => {
    const { container } = render(<StructuredArticleBody document={document} />);

    expect(
      [...container.querySelectorAll("[data-content-block-id]")].map((node) =>
        node.getAttribute("data-content-block-id"),
      ),
    ).toEqual(["p-1", "h-2", "q-3", "img-4", "l-5", "p-6"]);
    expect(screen.getByRole("heading", { name: "Inside the building", level: 2 })).toBeInTheDocument();
    expect(screen.getByText("A radical building.").closest("blockquote")).not.toBeNull();
    expect(screen.getByRole("list").tagName).toBe("OL");
  });

  it("renders an inline image with stable layout, caption, credit, and privacy policy", () => {
    render(<StructuredArticleBody document={document} />);

    const image = screen.getByRole("img", { name: "Trading floor" });
    expect(image).toHaveAttribute("src", "https://i.guim.co.uk/floor.jpg");
    expect(image).toHaveAttribute("loading", "lazy");
    expect(image).toHaveAttribute("decoding", "async");
    expect(image).toHaveAttribute("referrerpolicy", "no-referrer");
    expect(image).toHaveAttribute("width", "1200");
    expect(image).toHaveAttribute("height", "800");
    expect(screen.getByText("The main trading floor")).toBeInTheDocument();
    expect(screen.getByText("Photograph: Example")).toBeInTheDocument();
  });

  it("keeps the caption visible when one image fails", () => {
    render(<StructuredArticleBody document={document} />);
    fireEvent.error(screen.getByRole("img", { name: "Trading floor" }));

    expect(screen.queryByRole("img", { name: "Trading floor" })).not.toBeInTheDocument();
    expect(screen.getByText("图片暂时无法加载")).toBeInTheDocument();
    expect(screen.getByText("The main trading floor")).toBeInTheDocument();
  });
});
