import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { getProfile, resetProfile } from "../api/client";
import type { NewsSpace, ProfileResponse, ProfileTopicEvidence } from "../api/types";
import { localizeCategoryName, localizeInterfaceError } from "../localization";

interface Props {
  sourceSpace: NewsSpace;
  userId: number;
  refreshTick: number;
  onReset: () => void;
  variant?: "rail" | "page";
}

const STATUS_LABELS: Record<ProfileResponse["status"], string> = {
  cold: "刚开始了解你",
  learning: "持续学习",
  established: "画像较稳定",
};

const SIGNAL_LABELS: Record<string, string> = {
  recommendation_click: "推荐点击",
  search_result_click: "搜索点击",
  upvote: "点赞",
  downvote: "点踩",
  dwell: "深度阅读",
};

function evidenceExplanation(topic: ProfileTopicEvidence): string {
  const evidence = Object.entries(topic.signal_counts)
    .filter(([, count]) => count > 0)
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([signal, count]) => `${SIGNAL_LABELS[signal] ?? "互动"} ${count} 次`);
  return evidence.length > 0 ? evidence.join(" · ") : "正在积累兴趣依据";
}

function TopicGroup({
  title,
  topics,
  tone = "positive",
  scoreTotal,
}: {
  title: string;
  topics: ProfileTopicEvidence[];
  tone?: "positive" | "negative";
  scoreTotal?: number | null;
}) {
  const [expanded, setExpanded] = useState(false);
  if (topics.length === 0) return null;
  const weights = topics.map((topic) => Number.isFinite(topic.score)
    ? Math.max(0, tone === "negative" ? -topic.score : topic.score) : 0);
  // Normalize before folding; the backend denominator also includes omitted top-k topics.
  // Older servers without a total fall back to all returned topics in this group.
  const returnedTotal = weights.reduce((sum, weight) => sum + weight, 0);
  const total = typeof scoreTotal === "number" && Number.isFinite(scoreTotal)
    ? Math.max(returnedTotal, scoreTotal) : returnedTotal;
  const shares = topics.map((topic, index) => ({
    topic,
    percent: total > 0 ? Math.round((weights[index] / total) * 1000) / 10 : 0,
  }));
  const visibleTopics = expanded ? shares : shares.slice(0, 5);

  return (
    <section className="zr-profile-group" aria-label={title}>
      <div className="zr-profile-group__heading">
        <h3>{title}</h3>
        <span>{topics.length}</span>
      </div>
      <p className="zr-profile-updating">
        {tone === "negative" ? "本组减少推荐强度占比，独立于正向兴趣" : "同层兴趣占比，非预测概率；折叠不影响计算"}
      </p>
      <div className="zr-profile-topic-list">
        {visibleTopics.map(({ topic, percent }) => (
          <article
            className={`zr-profile-topic zr-profile-topic--${tone}`}
            key={topic.topic_id}
          >
            <div className="zr-profile-topic__line">
              <strong>{localizeCategoryName(topic.display_name)}</strong>
              <span>{percent}%</span>
            </div>
            <div className="zr-profile-topic__track" aria-hidden="true">
              <span style={{ width: `${percent}%` }} />
            </div>
            <p>{evidenceExplanation(topic)}</p>
          </article>
        ))}
      </div>
      {topics.length > 5 && (
        <button
          className="zr-profile-text-action"
          type="button"
          onClick={() => setExpanded((value) => !value)}
          aria-expanded={expanded}
          aria-label={`${expanded ? "收起" : "展开"}${title}`}
        >
          {expanded ? "收起" : `查看全部 ${topics.length} 项`}
        </button>
      )}
    </section>
  );
}

function reducedTopics(data: ProfileResponse): ProfileTopicEvidence[] {
  const byTopic = new Map<number, ProfileTopicEvidence>();
  for (const topic of [
    ...data.short_term.reduced_topics,
    ...data.long_term.reduced_topics,
  ]) {
    const existing = byTopic.get(topic.topic_id);
    if (!existing || Math.abs(topic.score) > Math.abs(existing.score)) {
      byTopic.set(topic.topic_id, topic);
    }
  }
  return [...byTopic.values()].sort((left, right) => left.score - right.score);
}

export default function ProfilePanel({
  sourceSpace,
  userId,
  refreshTick,
  onReset,
  variant = "rail",
}: Props) {
  const [data, setData] = useState<ProfileResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmingReset, setConfirmingReset] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [reloadTick, setReloadTick] = useState(0);
  const cancelLoad = useRef<(() => void) | undefined>();

  const load = useCallback(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let followUps = 0;
    setLoading(true);
    setError(null);
    setData(null);
    const refresh = () => {
      getProfile(sourceSpace, userId)
        .then((profile) => {
          if (
            active &&
            profile.source_space === sourceSpace &&
            profile.user_id === userId
          ) {
            setData(profile);
            setError(null);
          }
        })
        .catch((requestError: Error) => {
          if (active) setError(requestError.message);
        })
        .finally(() => {
          if (active) setLoading(false);
          if (active && sourceSpace === "live" && followUps < 5) {
            followUps += 1;
            timer = setTimeout(refresh, 2000);
          }
        });
    };
    refresh();
    return () => {
      active = false;
      if (timer) clearTimeout(timer);
    };
  }, [sourceSpace, userId]);

  useEffect(() => {
    const cancel = load();
    cancelLoad.current = cancel;
    return cancel;
  }, [load, refreshTick, reloadTick]);

  const reduced = useMemo(() => (data ? reducedTopics(data) : []), [data]);
  const isEmpty =
    data !== null &&
    data.short_term.interests.length === 0 &&
    data.long_term.interests.length === 0 &&
    reduced.length === 0;

  const handleReset = async () => {
    if (!confirmingReset) {
      setConfirmingReset(true);
      setError(null);
      return;
    }
    setResetting(true);
    cancelLoad.current?.();
    setError(null);
    try {
      const profile = await resetProfile(sourceSpace, userId);
      if (profile.source_space !== sourceSpace || profile.user_id !== userId) return;
      setData(profile);
      setConfirmingReset(false);
      onReset();
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : "请求失败");
    } finally {
      setResetting(false);
    }
  };

  if (loading && !data) {
    return <div className="zr-rail-card zr-status">正在整理你的兴趣画像…</div>;
  }
  if (!data && error) {
    return (
      <div className="zr-rail-card zr-status" role="alert">
        <p>兴趣画像加载失败：{localizeInterfaceError(error)}</p>
        <button className="zr-profile-text-action" type="button" onClick={() => setReloadTick((tick) => tick + 1)}>
          重新加载
        </button>
      </div>
    );
  }
  if (!data) return null;

  const confidence = Math.round(data.confidence * 100);
  return (
    <section
      className={`zr-rail-card zr-profile-panel${
        variant === "page" ? " zr-profile-panel--page" : ""
      }`}
      aria-labelledby="profile-v2-title"
    >
      <header className="zr-profile-header">
        <span className="zr-eyebrow">为你持续更新</span>
        <h2 id="profile-v2-title">我的兴趣画像</h2>
        <p className="zr-profile-space">
          {sourceSpace === "mind" ? "MIND 新闻空间" : "实时新闻空间"}
        </p>
        <div className="zr-profile-confidence">
          <span>{STATUS_LABELS[data.status]}</span>
          <strong title="根据互动证据数量计算，不代表画像准确率">{confidence}% {sourceSpace === "live" ? "画像积累度" : "置信度"}</strong>
        </div>
        <div
          className="zr-profile-confidence__track"
          role="progressbar"
          aria-label={sourceSpace === "live" ? "画像积累度" : "画像置信度"}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={confidence}
        >
          <span style={{ width: `${confidence}%` }} />
        </div>
        <p className="zr-profile-evidence-total">已参考 {data.evidence_count} 次{sourceSpace === "live" ? "有主题依据的互动" : "有效互动"}</p>
      </header>

      {loading && <p className="zr-profile-updating">正在同步最新变化…</p>}
      {isEmpty ? (
        <div className="zr-profile-empty">
          <strong>你的画像还很轻</strong>
          <p>
            {sourceSpace === "live"
              ? "阅读记录已独立保存。新闻主题分析完成后，点击和深度阅读将形成短期与长期兴趣；主题不明确的内容仅保留最近活动。"
              : "阅读、搜索、停留或点踩后，这里会逐渐形成可解释的兴趣主题。"}
          </p>
        </div>
      ) : (
        <div className="zr-profile-groups">
          <TopicGroup title="短期兴趣" topics={data.short_term.interests} scoreTotal={data.short_term.positive_score_total} />
          <TopicGroup title="长期兴趣" topics={data.long_term.interests} scoreTotal={data.long_term.positive_score_total} />
          <TopicGroup title="减少推荐" topics={reduced} tone="negative" />
        </div>
      )}

      {sourceSpace === "live" && data.recent_clicked_news.length > 0 && (
        <section className="zr-profile-recent" aria-labelledby="profile-recent-title">
          <h3 id="profile-recent-title">最近活动</h3>
          <div className="zr-recent-list">
            {data.recent_clicked_news.map((news, index) => (
              <div key={`${news.news_id}-${index}`} className="zr-recent-row">
                <Link to={`/articles/live/${news.news_id}`} className="zr-recent-link">
                  {news.title ?? news.news_id}
                </Link>
                <time>{new Date(news.click_ts * 1000).toLocaleDateString("zh-CN")}</time>
              </div>
            ))}
          </div>
        </section>
      )}

      <footer className="zr-profile-reset">
        {confirmingReset && (
          <p>此操作会恢复冷启动画像，历史事件仍会保留。</p>
        )}
        {error && <p className="zr-profile-error" role="alert">{localizeInterfaceError(error)}</p>}
        <div className="zr-profile-reset__actions">
          <button
            className="zr-profile-reset-button"
            type="button"
            disabled={resetting}
            onClick={() => void handleReset()}
          >
            {resetting ? "正在重置…" : confirmingReset ? "确认重置" : "重置画像"}
          </button>
          {confirmingReset && !resetting && (
            <button
              className="zr-profile-text-action"
              type="button"
              onClick={() => {
                setConfirmingReset(false);
                setError(null);
              }}
            >
              取消
            </button>
          )}
        </div>
      </footer>
    </section>
  );
}
