import { useEffect, useMemo, useState } from "react";
import { getProfile, resetProfile } from "../api/client";
import type { ProfileResponse, ProfileTopicEvidence } from "../api/types";
import { localizeCategoryName, localizeInterfaceError } from "../localization";

interface Props {
  refreshTick: number;
  onReset: () => void;
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
}: {
  title: string;
  topics: ProfileTopicEvidence[];
  tone?: "positive" | "negative";
}) {
  const [expanded, setExpanded] = useState(false);
  if (topics.length === 0) return null;
  const visibleTopics = expanded ? topics : topics.slice(0, 5);

  return (
    <section className="zr-profile-group" aria-label={title}>
      <div className="zr-profile-group__heading">
        <h3>{title}</h3>
        <span>{topics.length}</span>
      </div>
      <div className="zr-profile-topic-list">
        {visibleTopics.map((topic) => (
          <article
            className={`zr-profile-topic zr-profile-topic--${tone}`}
            key={topic.topic_id}
          >
            <div className="zr-profile-topic__line">
              <strong>{localizeCategoryName(topic.display_name)}</strong>
              <span>{Math.round(Math.abs(topic.score) * 100)}%</span>
            </div>
            <div className="zr-profile-topic__track" aria-hidden="true">
              <span style={{ width: `${Math.min(100, Math.abs(topic.score) * 100)}%` }} />
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

export default function ProfilePanel({ refreshTick, onReset }: Props) {
  const [data, setData] = useState<ProfileResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmingReset, setConfirmingReset] = useState(false);
  const [resetting, setResetting] = useState(false);

  const load = () => {
    let active = true;
    setLoading(true);
    setError(null);
    getProfile()
      .then((profile) => {
        if (active) setData(profile);
      })
      .catch((requestError: Error) => {
        if (active) setError(requestError.message);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  };

  useEffect(load, [refreshTick]);

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
    setError(null);
    try {
      const profile = await resetProfile();
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
        <button className="zr-profile-text-action" type="button" onClick={load}>
          重新加载
        </button>
      </div>
    );
  }
  if (!data) return null;

  const confidence = Math.round(data.confidence * 100);
  return (
    <section className="zr-rail-card zr-profile-panel" aria-labelledby="profile-v2-title">
      <header className="zr-profile-header">
        <span className="zr-eyebrow">为你持续更新</span>
        <h2 id="profile-v2-title">我的兴趣画像</h2>
        <div className="zr-profile-confidence">
          <span>{STATUS_LABELS[data.status]}</span>
          <strong>{confidence}% 置信度</strong>
        </div>
        <div
          className="zr-profile-confidence__track"
          role="progressbar"
          aria-label="画像置信度"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={confidence}
        >
          <span style={{ width: `${confidence}%` }} />
        </div>
        <p className="zr-profile-evidence-total">已参考 {data.evidence_count} 次有效互动</p>
      </header>

      {loading && <p className="zr-profile-updating">正在同步最新变化…</p>}
      {isEmpty ? (
        <div className="zr-profile-empty">
          <strong>你的画像还很轻</strong>
          <p>阅读、搜索、停留或点踩后，这里会逐渐形成可解释的兴趣主题。</p>
        </div>
      ) : (
        <div className="zr-profile-groups">
          <TopicGroup title="短期兴趣" topics={data.short_term.interests} />
          <TopicGroup title="长期兴趣" topics={data.long_term.interests} />
          <TopicGroup title="减少推荐" topics={reduced} tone="negative" />
        </div>
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
