import { ArrowLeft } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import {
  ensureArticleContent,
  getArticleCard,
  newClientId,
  sendTrackedEventKeepalive,
  trackEvent,
} from "../api/client";
import type {
  ArticleCardResponse,
  ArticleEntity,
  ArticleEntityType,
  NewsSpace,
} from "../api/types";
import { usePersona } from "../context/PersonaContext";
import { useSourceSpace } from "../context/SourceSpaceContext";
import StructuredArticleBody from "../components/StructuredArticleBody";
import { localizeCategoryName, localizeInterfaceError } from "../localization";
import { dwellEventId, VisibleDwellAccumulator } from "../profile/visibleDwell";
import ReadingActions from "../reading/ReadingActions";

const entityGroupLabels: Record<ArticleEntityType, string> = {
  person: "人物",
  organization: "机构",
  location: "地点",
  other: "其他实体",
};

const BODY_ERRORS: Record<string, string> = {
  authentication_required: "原站要求登录或拒绝访问，请阅读原文。",
  api_tier_restricted: "当前 API 不提供此文章，网页备用获取未启用或不可用。",
  paywall_or_login: "原站正文需要登录或订阅，请阅读原文。",
  publisher_blocked: "原站不允许当前抓取方式，请阅读原文。",
  unsupported_template: "暂未识别原站正文结构，请阅读原文。",
  extraction_quality_failed: "正文抽取结果未通过校验，请阅读原文。",
  article_not_found: "原站文章暂不可用，请检查原文链接。",
  local_research_disabled: "此正文仅在启用本地研究模式时可见。",
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

function validArticleRoute(sourceSpace: string, articleId: string): sourceSpace is NewsSpace {
  if (sourceSpace === "mind") return /^N\d+$/.test(articleId);
  if (sourceSpace === "live") return /^L[0-9a-f]{32}$/.test(articleId);
  return false;
}

function isFeedNavigationState(
  value: unknown,
): value is { fromFeed: true; feedContextKey: string } {
  return (
    typeof value === "object" &&
    value !== null &&
    "fromFeed" in value &&
    value.fromFeed === true &&
    "feedContextKey" in value &&
    typeof value.feedContextKey === "string" &&
    value.feedContextKey.length > 0
  );
}

export default function ArticleDetailPage() {
  const location = useLocation();
  const navigate = useNavigate();
  const { sourceSpace: routeSource, articleId: routeArticleId, newsId } = useParams<{
    sourceSpace?: string;
    articleId?: string;
    newsId?: string;
  }>();
  const sourceSpace = (routeSource ?? "mind") as NewsSpace;
  const articleId = routeArticleId ?? newsId ?? "";
  const routeIsValid = validArticleRoute(sourceSpace, articleId);
  const { selectedPersona, bumpProfile } = usePersona();
  const { selectSourceSpace } = useSourceSpace();
  const [data, setData] = useState<ArticleCardResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [imageFailed, setImageFailed] = useState(false);
  const [bodyPollingExhausted, setBodyPollingExhausted] = useState(false);
  const outboundTrackedRef = useRef(false);
  const ensureRequestedRef = useRef(false);
  const detailTrackedRef = useRef(false);
  const routeLoadId = useMemo(
    () => newClientId("article-detail"),
    [sourceSpace, articleId],
  );

  useEffect(() => {
    if (!routeIsValid) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setData(null);
    setImageFailed(false);
    setBodyPollingExhausted(false);
    outboundTrackedRef.current = false;
    ensureRequestedRef.current = false;
    detailTrackedRef.current = false;
    getArticleCard(articleId, sourceSpace)
      .then((res) => {
        if (
          cancelled ||
          res.source_space !== sourceSpace ||
          res.article_id !== articleId
        ) {
          return;
        }
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
  }, [articleId, routeIsValid, sourceSpace]);

  useEffect(() => {
    if (
      !data ||
      sourceSpace !== "live" ||
      data.body_document ||
      !["missing", "failed"].includes(data.body_structure_status ?? "missing") ||
      data.content_rights === "link_only" ||
      (data.body_error_code && BODY_ERRORS[data.body_error_code]) ||
      ensureRequestedRef.current
    ) {
      return;
    }
    ensureRequestedRef.current = true;
    void ensureArticleContent(sourceSpace, articleId)
      .then((response) => {
        setData((current) =>
          current
            ? { ...current, body_structure_status: response.status }
            : current,
        );
      })
      .catch(() => undefined);
  }, [articleId, data, sourceSpace]);

  useEffect(() => {
    if (!data || sourceSpace !== "live" || data.body_structure_status !== "pending") return;
    let cancelled = false;
    let attempts = 0;
    let inFlight = false;
    const interval = window.setInterval(() => {
      if (attempts >= 12) {
        window.clearInterval(interval);
        setBodyPollingExhausted(true);
        return;
      }
      attempts += 1;
      if (document.visibilityState === "hidden" || inFlight) return;
      inFlight = true;
      void getArticleCard(articleId, sourceSpace)
        .then((response) => {
          if (!cancelled && response.article_id === articleId && response.source_space === sourceSpace) setData(response);
        })
        .catch(() => undefined)
        .finally(() => { inFlight = false; });
    }, 5_000);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [articleId, data?.body_structure_status, sourceSpace]);

  useEffect(() => {
    if (!data || !selectedPersona || detailTrackedRef.current) return;
    detailTrackedRef.current = true;
    void trackEvent({
      event_id: `detail-${sourceSpace}:${selectedPersona.user_id}:${articleId}:${routeLoadId}`,
      user_id: selectedPersona.user_id,
      source_space: sourceSpace,
      event_type: "detail_view",
      surface: "article_detail",
      article_id: articleId,
    })
      .then(() => bumpProfile())
      .catch(() => undefined);
  }, [articleId, data, routeLoadId, selectedPersona, sourceSpace, bumpProfile]);

  useEffect(() => {
    const userId = selectedPersona?.user_id;
    const loadedArticleId = data?.article_id;
    if (!userId || !loadedArticleId) return;

    const dwell = new VisibleDwellAccumulator(
      () => performance.now(),
      document.visibilityState === "visible",
    );
    const flush = () => {
      const dwellMs = dwell.takeForSend(10_000);
      if (dwellMs === null) return;
      try {
        sendTrackedEventKeepalive({
          event_id: dwellEventId(sourceSpace, userId, loadedArticleId, routeLoadId),
          user_id: userId,
          source_space: sourceSpace,
          event_type: "dwell",
          surface: "article_detail",
          article_id: loadedArticleId,
          dwell_ms: dwellMs,
        });
      } catch {
        // Unload feedback is best-effort and must never block navigation.
      }
    };
    const handleVisibility = () => {
      dwell.setVisible(document.visibilityState === "visible");
    };
    const handlePageHide = () => {
      dwell.setVisible(false);
      flush();
    };

    document.addEventListener("visibilitychange", handleVisibility);
    window.addEventListener("pagehide", handlePageHide);
    return () => {
      document.removeEventListener("visibilitychange", handleVisibility);
      window.removeEventListener("pagehide", handlePageHide);
      flush();
    };
  }, [data?.article_id, selectedPersona?.user_id, routeLoadId, sourceSpace]);

  const handleOutboundClick = () => {
    if (!selectedPersona || outboundTrackedRef.current) return;
    outboundTrackedRef.current = true;
    void trackEvent({
      event_id: `outbound-${sourceSpace}:${selectedPersona.user_id}:${articleId}:${routeLoadId}`,
      user_id: selectedPersona.user_id,
      source_space: sourceSpace,
      event_type: "outbound_click",
      surface: "article_detail",
      article_id: articleId,
    }).catch(() => {
      outboundTrackedRef.current = false;
    });
  };

  if (!routeIsValid) {
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
  const bodyParagraphs = (data.body_text ?? "")
    .split(/\n\s*\n/)
    .map((paragraph) => paragraph.trim())
    .filter(Boolean);
  const handleReturnToFeed = () => {
    if (isFeedNavigationState(location.state)) {
      navigate(-1);
      return;
    }
    selectSourceSpace(sourceSpace);
    navigate("/", { replace: true });
  };

  return (
    <main className="zr-center zr-article-page">
      <div className="zr-post-detail">
        <button
          type="button"
          className="zr-back-link zr-back-link--sticky"
          onClick={handleReturnToFeed}
        >
          <ArrowLeft size={14} />
          返回信息流
        </button>

        <div className="zr-card__meta">
          {mainCategory && (
            <span className="zr-card__community">
              <span className="zr-category-dot" aria-hidden="true" />
              {localizeCategoryName(mainCategory.display_name)}
            </span>
          )}
          <span>来源：{data.publisher ?? data.source_domain}</span>
          {data.language && <span>{data.language === "zh" ? "中文" : "English"}</span>}
          {data.published_at && (
            <time dateTime={data.published_at}>
              {new Date(data.published_at).toLocaleString("zh-CN")}
            </time>
          )}
        </div>

        <h1 className="zr-post-detail__title">{data.title}</h1>
        <ReadingActions sourceSpace={data.source_space} articleId={data.article_id} />

        {data.image_url && !imageFailed && (
          <img
            className="zr-post-detail__image"
            src={data.image_url}
            alt={data.title}
            onError={() => setImageFailed(true)}
          />
        )}

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
          {data.body_structure_status === "pending" && bodyParagraphs.length > 0 && (
            <p className="zr-post-detail__body-state">正在优化图文排版</p>
          )}
          {data.body_document ? (
            <section className="zr-post-detail__body" aria-labelledby="article-body-title">
              {data.body_access_scope === "local_research" && (
                <span className="zr-local-research-label">本地研究正文</span>
              )}
              <h2 id="article-body-title" className="zr-eyebrow">
                正文
              </h2>
              <StructuredArticleBody document={data.body_document} />
            </section>
          ) : bodyParagraphs.length > 0 ? (
            <section className="zr-post-detail__body" aria-labelledby="article-body-title">
              {data.body_access_scope === "local_research" && (
                <span className="zr-local-research-label">本地研究正文</span>
              )}
              <h2 id="article-body-title" className="zr-eyebrow">
                正文
              </h2>
              <div className="zr-post-detail__body-copy">
                {bodyParagraphs.map((paragraph, index) => (
                  <p key={`${index}:${paragraph.slice(0, 32)}`}>{paragraph}</p>
                ))}
              </div>
            </section>
          ) : data.body_structure_status === "pending" || data.body_status === "pending" ? (
            <p className="zr-post-detail__body-state">{bodyPollingExhausted ? "正文仍在后台处理，可稍后刷新或阅读原文。" : data.body_error_code === "network_error" ? "正文获取遇到网络问题，正在重试…" : "正文正在获取中…"}</p>
          ) : data.body_status === "blocked" || data.body_status === "failed" || data.body_error_code ? (
            <p className="zr-post-detail__body-state">{BODY_ERRORS[data.body_error_code ?? ""] ?? "正文暂时无法获取，可稍后重试或阅读原文。"}</p>
          ) : null}
          <a
            href={data.url}
            target="_blank"
            rel="noreferrer noopener"
            className="zr-action"
            onClick={handleOutboundClick}
          >
            阅读原文
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
