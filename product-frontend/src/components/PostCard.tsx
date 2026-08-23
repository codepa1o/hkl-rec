import { Check, Newspaper, Share2 } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { trackEvent } from "../api/client";
import type { FeedItem, SearchItem } from "../api/types";
import { localizeCategoryName, localizeRecommendationReason } from "../localization";
import VoteActions from "./VoteActions";

interface Props {
  item: FeedItem | SearchItem;
  userId: number;
  requestId?: string;
  surface?: string;
  showReason?: boolean;
  onTrackClick?: () => void;
  onProfileChanged?: () => void;
  feedNavigationState?: {
    fromFeed: true;
    feedContextKey: string;
  };
  onOpenArticle?: (articleId: string) => void;
}

function isFeedItem(item: FeedItem | SearchItem): item is FeedItem {
  return "selected_reason" in item;
}

export default function PostCard({
  item,
  userId,
  requestId,
  surface = "feed",
  showReason,
  onTrackClick,
  onProfileChanged,
  feedNavigationState,
  onOpenArticle,
}: Props) {
  const [shared, setShared] = useState(false);
  const [imageFailed, setImageFailed] = useState(false);
  const mainCategory = item.categories?.[0];
  const categoryName = localizeCategoryName(mainCategory?.display_name);

  useEffect(() => setImageFailed(false), [item.article_id]);

  const articlePath = `/articles/${item.source_space}/${item.article_id}`;
  const handleOpenArticle = () => {
    onOpenArticle?.(item.article_id);
    onTrackClick?.();
  };
  const handleShare = async () => {
    const url = `${window.location.origin}${articlePath}`;
    if (navigator.share) {
      await navigator.share({ title: item.title, url });
    } else {
      await navigator.clipboard.writeText(url);
    }
    setShared(true);
    window.setTimeout(() => setShared(false), 1600);
    await trackEvent({
      user_id: userId,
      source_space: item.source_space,
      event_type: "share",
      surface,
      article_id: item.article_id,
      request_id: requestId ?? null,
    });
  };

  return (
    <article className="zr-card" data-article-id={item.article_id}>
      <div className="zr-card__body">
        <div className="zr-card__meta">
          <span className="zr-card__community">
            <span className="zr-category-dot" aria-hidden="true" />
            {categoryName}
          </span>
          {isFeedItem(item) && item.content_type === "sponsored" && (
            <span className="zr-card__sponsored">
              {item.sponsored?.label
                ? localizeCategoryName(item.sponsored.label)
                : "赞助内容"}
            </span>
          )}
          <span className="zr-card__source">
            来源：{item.publisher ?? item.source_domain}
            {item.language ? ` · ${item.language === "zh" ? "中文" : "English"}` : ""}
          </span>
          {item.source_space === "live" && (item.published_at || item.discovered_at) && (
            <time dateTime={item.published_at ?? item.discovered_at ?? undefined}>
              {new Date(item.published_at ?? item.discovered_at ?? "").toLocaleString(
                "zh-CN",
              )}
            </time>
          )}
        </div>

        {item.source_space === "live" && item.image_url && !imageFailed && (
          <img
            className="zr-card__image"
            src={item.image_url}
            alt={item.title}
            loading="lazy"
            onError={() => setImageFailed(true)}
          />
        )}

        <h2 className="zr-card__title">
          <Link
            to={articlePath}
            state={feedNavigationState}
            onClick={handleOpenArticle}
          >
            {item.title}
          </Link>
        </h2>

        <p className="zr-card__summary">{item.abstract}</p>

        {item.categories.length > 0 && (
          <div className="zr-card__chips" aria-label="文章分类">
            {item.categories.map((topic) => (
              <span key={topic.topic_id} className="zr-chip">
                {localizeCategoryName(topic.display_name)}
              </span>
            ))}
          </div>
        )}

        {showReason && isFeedItem(item) && item.selected_reason && (
          <div className="zr-card__reason">
            <span>推荐理由</span>
            {localizeRecommendationReason(item.selected_reason)}
          </div>
        )}

        <div className="zr-card__footer">
          <VoteActions
            sourceSpace={item.source_space}
            articleId={item.article_id}
            userId={userId}
            requestId={requestId}
            surface={surface}
            onVoted={onProfileChanged}
          />
          <div className="zr-card__actions">
            <Link
              to={articlePath}
              state={feedNavigationState}
              className="zr-action"
              onClick={handleOpenArticle}
            >
              <Newspaper size={15} />
              查看详情
            </Link>
            <button
              type="button"
              className="zr-action"
              aria-label="分享文章"
              onClick={() => void handleShare()}
            >
              {shared ? <Check size={15} /> : <Share2 size={15} />}
              {shared ? "已复制" : "分享"}
            </button>
          </div>
        </div>
      </div>
    </article>
  );
}
