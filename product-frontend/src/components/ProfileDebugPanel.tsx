import { Activity, BookOpen, Sparkles } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getDebugProfile } from "../api/client";
import type { DebugProfileResponse, NewsSpace } from "../api/types";
import { localizeInterfaceError } from "../localization";
import TopicWeightChart from "./TopicWeightChart";

interface Props {
  sourceSpace: NewsSpace;
  userId: number;
  refreshTick: number;
}

export default function ProfileDebugPanel({ sourceSpace, userId, refreshTick }: Props) {
  const [data, setData] = useState<DebugProfileResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    setData(null);
    getDebugProfile(userId, sourceSpace)
      .then((response) => {
        if (
          !cancelled &&
          response.source_space === sourceSpace &&
          response.user_id === userId
        ) {
          setData(response);
        }
      })
      .catch((requestError: Error) => {
        if (!cancelled) setError(requestError.message);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [sourceSpace, userId, refreshTick]);

  if (loading && !data) {
    return <div className="zr-rail-card zr-status">正在整理你的兴趣…</div>;
  }
  if (error) {
    return (
      <div className="zr-rail-card zr-status">
        兴趣画像加载失败：{localizeInterfaceError(error)}
      </div>
    );
  }
  if (!data) return null;

  const sortedWeights = [...data.topic_weights].sort((a, b) => b.weight - a.weight);

  return (
    <section className="zr-rail-card zr-interest-card" aria-labelledby="interest-title">
      <div className="zr-rail-card__heading">
        <div>
          <span className="zr-eyebrow">
            {sourceSpace === "mind" ? "MIND 个性化推荐" : "实时新闻独立画像"}
          </span>
          <h2 id="interest-title">你的兴趣</h2>
        </div>
        <Sparkles size={18} aria-hidden="true" />
      </div>

      <div className="zr-interest-score">
        <span className="zr-interest-score__icon">
          <Activity size={17} />
        </span>
        <span>
          <small>兴趣活跃度</small>
          <strong>{data.behavior_score.toFixed(1)}</strong>
        </span>
      </div>

      <div className="zr-interest-section">
        <div className="zr-interest-section__title">关注主题</div>
        <TopicWeightChart topicWeights={sortedWeights} limit={5} />
        {sortedWeights.length === 0 && <p className="zr-muted-copy">阅读后将逐渐形成兴趣画像。</p>}
      </div>

      {data.recent_clicked_news.length > 0 && (
        <div className="zr-interest-section">
          <div className="zr-interest-section__title">
            <BookOpen size={15} />
            最近阅读
          </div>
          <div className="zr-recent-list">
            {data.recent_clicked_news.map((news, index) => (
              <div key={`${news.news_id}-${index}`} className="zr-recent-row">
                <Link
                  to={`/articles/${sourceSpace}/${news.news_id}`}
                  className="zr-recent-link"
                  title={news.title ?? news.news_id}
                >
                  {news.title ?? news.news_id}
                </Link>
                <time>{new Date(news.click_ts * 1000).toLocaleDateString("zh-CN")}</time>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
