import { fireEvent, render, screen } from "@testing-library/react";
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
