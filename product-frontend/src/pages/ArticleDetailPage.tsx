import { ArrowLeft } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getArticleCard, trackEvent } from "../api/client";
import type { ArticleCardResponse, ArticleEntity, ArticleEntityType } from "../api/types";
import { usePersona } from "../context/PersonaContext";
import { localizeCategoryName, localizeInterfaceError } from "../localization";

const entityGroupLabels: Record<ArticleEntityType, string> = {
  person: "人物",
  organization: "机构",
  location: "地点",
  other: "其他实体",
};

function groupArticleEntities(data: ArticleCardResponse) {
  const unique = new Map<string, ArticleEntity>();
  [...data.title_entities, ...data.abstract_entities].forEach((entity) => {
    const key = entity.wikidata_id || `${entity.entity_type}:${entity.label.toLocaleLowerCase()}`;
    const existing = unique.get(key);
    if (!existing || (entity.confidence ?? 0) > (existing.confidence ?? 0)) {
      unique.set(key, entity);
    }
  });
  const order: ArticleEntityType[] = ["person", "organization", "location", "other"];
  return order
    .map((type) => ({
      type,
      label: entityGroupLabels[type],
      entities: [...unique.values()].filter((entity) => entity.entity_type === type),
    }))
    .filter((group) => group.entities.length > 0);
}

export default function ArticleDetailPage() {
  const { newsId } = useParams<{ newsId: string }>();
  const { selectedPersona, bumpProfile } = usePersona();
  const [data, setData] = useState<ArticleCardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!newsId || !/^N\d+$/.test(newsId)) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    getArticleCard(newsId)
      .then((res) => {
        if (cancelled) return;
        setData(res);
      })
      .catch((err: Error) => {
        if (cancelled) return;
        setError(err.message);
      })
      .finally(() => {
        if (cancelled) return;
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [newsId]);

  useEffect(() => {
    if (!data || !selectedPersona) return;
    trackEvent({
      user_id: selectedPersona.user_id,
      event_type: "detail_view",
      surface: "article_detail",
      news_id: data.news_id,
    }).then(() => bumpProfile());
  }, [data, selectedPersona, bumpProfile]);

  if (!newsId || !/^N\d+$/.test(newsId)) {
    return (
      <main className="zr-center">
        <div className="zr-status">文章编号无效。</div>
      </main>
    );
  }

  if (loading) {
    return (
      <main className="zr-center">
        <div className="zr-status">正在加载文章…</div>
      </main>
    );
  }

  if (error) {
    return (
      <main className="zr-center">
        <div className="zr-status">文章加载失败：{localizeInterfaceError(error)}</div>
      </main>
    );
  }

  if (!data) {
    return (
      <main className="zr-center">
        <div className="zr-status">未找到该文章。</div>
      </main>
    );
  }

  const mainCategory = data.categories?.[0];
  const entityGroups = groupArticleEntities(data);

  return (
    <main className="zr-center zr-article-page">
      <div className="zr-post-detail">
        <Link to="/" className="zr-back-link">
          <ArrowLeft size={14} />
          返回信息流
        </Link>

        <div className="zr-card__meta">
          {mainCategory && (
            <span className="zr-card__community">
              <span className="zr-category-dot" aria-hidden="true" />
              {localizeCategoryName(mainCategory.display_name)}
            </span>
          )}
          <span>来源：{data.source_domain}</span>
        </div>

        <h1 className="zr-post-detail__title">{data.title}</h1>

        {data.categories.length > 0 && (
          <div className="zr-card__chips">
            {data.categories.map((t) => (
              <span key={t.topic_id} className="zr-chip">
                {localizeCategoryName(t.display_name)}
              </span>
            ))}
          </div>
        )}

        <div className="zr-post-detail__content">
          <span className="zr-eyebrow">文章摘要</span>
          <div className="zr-post-detail__summary">{data.abstract}</div>
          <a href={data.url} target="_blank" rel="noreferrer" className="zr-action">
            MIND source
          </a>
        </div>

        {entityGroups.length > 0 && (
          <section className="zr-entities" aria-labelledby="article-entities-title">
            <h2 id="article-entities-title">相关实体</h2>
            <div className="zr-entities__groups">
              {entityGroups.map((group) => (
                <div key={group.type} className="zr-entities__group">
                  <h3>{group.label}</h3>
                  <div className="zr-entities__chips">
                    {group.entities.map((entity) => {
                      const content = (
                        <>
                          <span>{entity.label}</span>
                          {entity.wikidata_id && <small>{entity.wikidata_id}</small>}
                        </>
                      );
                      return entity.wikidata_id ? (
                        <a
                          key={entity.wikidata_id}
                          className="zr-entity-chip"
                          href={`https://www.wikidata.org/wiki/${encodeURIComponent(entity.wikidata_id)}`}
                          target="_blank"
                          rel="noreferrer"
                        >
                          {content}
                        </a>
                      ) : (
                        <span
                          key={`${entity.entity_type}:${entity.label}`}
                          className="zr-entity-chip"
                        >
                          {content}
                        </span>
                      );
                    })}
                  </div>
                </div>
              ))}
            </div>
          </section>
        )}
      </div>
    </main>
  );
}
