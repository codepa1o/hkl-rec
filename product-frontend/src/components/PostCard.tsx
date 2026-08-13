import { Check, Newspaper, Share2 } from "lucide-react";
import { useState } from "react";
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
}: Props) {
  const [shared, setShared] = useState(false);
  const mainCategory = item.categories?.[0];
  const categoryName = localizeCategoryName(mainCategory?.display_name);

  const handleShare = async () => {
    const url = `${window.location.origin}/articles/${item.article_id}`;
    if (navigator.share) {
      await navigator.share({ title: item.headline, url });
    } else {
      await navigator.clipboard.writeText(url);
    }
    setShared(true);
    window.setTimeout(() => setShared(false), 1600);
    await trackEvent({
      user_id: userId,
      event_type: "share",
      surface,
      article_id: item.article_id,
      request_id: requestId ?? null,
    });
  };

  return (
    <article className="zr-card">
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
            <span className="zr-card__source">来源：{item.source_domain}</span>
        </div>

        <h2 className="zr-card__title">
          <Link to={`/articles/${item.article_id}`} onClick={onTrackClick}>
            {item.headline}
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
            articleId={item.article_id}
            userId={userId}
            requestId={requestId}
            surface={surface}
            onVoted={onProfileChanged}
          />
          <div className="zr-card__actions">
            <Link
              to={`/articles/${item.article_id}`}
              className="zr-action"
              onClick={onTrackClick}
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
