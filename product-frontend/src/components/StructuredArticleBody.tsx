import { useState } from "react";
import { resolveArticleImageUrl } from "../api/client";
import type {
  ImageContentBlock,
  StructuredBodyDocument,
  StructuredContentBlock,
} from "../api/types";

function ArticleImageBlock({ block }: { block: ImageContentBlock }) {
  const [failed, setFailed] = useState(false);
  const imageUrl = resolveArticleImageUrl(block.display_url ?? block.source_url);
  return (
    <figure className="zr-article-figure" data-content-block-id={block.id}>
      {failed || !imageUrl || block.cache_status === "omitted" ? (
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
  const publishedAt = document.published_at && Number.isFinite(Date.parse(document.published_at))
    ? document.published_at : undefined;
  const hasMetadata = document.source === "html" || Boolean(document.byline) || Boolean(publishedAt);
  const tags = (document.publisher_tags ?? []).filter((tag) => {
    try {
      const url = new URL(tag.url);
      return url.protocol === "https:" && !url.username && !url.password;
    } catch {
      return false;
    }
  });
  return (
    <div className="zr-structured-article-body">
      {hasMetadata && (
        <div className="zr-article-metadata" role="group" aria-label="正文来源信息">
          {document.source === "html" && (
            <div className="zr-article-metadata__source">
              <span className="zr-article-metadata__label">来源</span>
              <span>原站网页</span>
              {document.fallback_reason && (
                <span className="zr-article-metadata__hint">API 未提供正文，已使用网页备用获取</span>
              )}
            </div>
          )}
          {(document.byline || publishedAt) && (
            <dl className="zr-article-metadata__details">
              {document.byline && (
                <div className="zr-article-metadata__item">
                  <dt>作者</dt><dd>{document.byline}</dd>
                </div>
              )}
              {publishedAt && (
                <div className="zr-article-metadata__item">
                  <dt>原文发布</dt>
                  <dd><time dateTime={publishedAt} title={new Date(publishedAt).toLocaleString("zh-CN")}>
                    {new Date(publishedAt).toLocaleString("zh-CN", {
                      year: "numeric", month: "2-digit", day: "2-digit",
                      hour: "2-digit", minute: "2-digit", hourCycle: "h23",
                    })}
                  </time></dd>
                </div>
              )}
            </dl>
          )}
        </div>
      )}
      {(document.warnings ?? []).map((warning, index) => <p className="zr-article-source-note" key={index}>{warning}</p>)}
      {document.blocks.map((block) => (
        <ContentBlock key={block.id} block={block} />
      ))}
      {tags.length > 0 && (
        <section className="zr-publisher-tags" aria-label="原站话题标签">
          <h2>原站话题</h2>
          <div className="zr-publisher-tags__items">
            {tags.map((tag) => <a className="zr-publisher-tag" key={tag.url} href={tag.url} target="_blank" rel="noopener noreferrer">{tag.name}</a>)}
          </div>
        </section>
      )}
    </div>
  );
}
