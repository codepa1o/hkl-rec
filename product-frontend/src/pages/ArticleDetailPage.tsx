import { ArrowLeft } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getArticleCard, trackEvent } from "../api/client";
import type { ArticleCardResponse } from "../api/types";
import { usePersona } from "../context/PersonaContext";
import { localizeCategoryName, localizeInterfaceError } from "../localization";

export default function ArticleDetailPage() {
  const { articleId: articleIdParam } = useParams<{ articleId: string }>();
  const articleId = Number(articleIdParam);
  const { selectedPersona, bumpProfile } = usePersona();
  const [data, setData] = useState<ArticleCardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!articleId || isNaN(articleId)) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    getArticleCard(articleId)
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
  }, [articleId]);

  useEffect(() => {
    if (!data || !selectedPersona) return;
    trackEvent({
      user_id: selectedPersona.user_id,
      event_type: "detail_view",
      surface: "article_detail",
      article_id: data.article_id,
    }).then(() => bumpProfile());
  }, [data, selectedPersona, bumpProfile]);

  if (isNaN(articleId)) {
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

        <h1 className="zr-post-detail__title">{data.headline}</h1>

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
        </div>
      </div>
    </main>
  );
}
