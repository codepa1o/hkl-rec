import { useState } from "react";
import type {
  ImageContentBlock,
  StructuredBodyDocument,
  StructuredContentBlock,
} from "../api/types";

function ArticleImageBlock({ block }: { block: ImageContentBlock }) {
  const [failed, setFailed] = useState(false);
  const imageUrl = block.display_url ?? block.source_url;
  return (
    <figure className="zr-article-figure" data-content-block-id={block.id}>
      {failed || block.cache_status === "omitted" ? (
        <div className="zr-article-figure__placeholder">图片暂时无法加载</div>
      ) : (
        <img
          src={imageUrl}
          alt={block.alt ?? ""}
          width={block.width ?? undefined}
          height={block.height ?? undefined}
          loading="lazy"
          decoding="async"
          referrerPolicy="no-referrer"
          onError={() => setFailed(true)}
        />
      )}
      {(block.caption || block.credit) && (
        <figcaption>
          {block.caption && <span>{block.caption}</span>}
          {block.credit && <cite>{block.credit}</cite>}
        </figcaption>
      )}
    </figure>
  );
}

function ContentBlock({ block }: { block: StructuredContentBlock }) {
  switch (block.type) {
    case "paragraph":
      return <p data-content-block-id={block.id}>{block.text}</p>;
    case "heading":
      if (block.level === 2) return <h2 data-content-block-id={block.id}>{block.text}</h2>;
      if (block.level === 3) return <h3 data-content-block-id={block.id}>{block.text}</h3>;
      return <h4 data-content-block-id={block.id}>{block.text}</h4>;
    case "quote":
      return (
        <blockquote data-content-block-id={block.id}>
          <p>{block.text}</p>
          {block.attribution && <cite>{block.attribution}</cite>}
        </blockquote>
      );
    case "list": {
      const Tag = block.ordered ? "ol" : "ul";
      return (
        <Tag data-content-block-id={block.id}>
          {block.items.map((item, index) => (
            <li key={`${index}:${item.slice(0, 32)}`}>{item}</li>
          ))}
        </Tag>
      );
    }
    case "image":
      return <ArticleImageBlock block={block} />;
    default:
      return null;
  }
}

export default function StructuredArticleBody({
  document,
}: {
  document: StructuredBodyDocument;
}) {
  return (
    <div className="zr-structured-article-body">
      {document.blocks.map((block) => (
        <ContentBlock key={block.id} block={block} />
      ))}
    </div>
  );
}
