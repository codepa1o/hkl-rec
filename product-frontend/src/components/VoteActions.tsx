import { ArrowDown, ArrowUp } from "lucide-react";
import { useState } from "react";
import { trackEvent } from "../api/client";

interface Props {
  newsId: string;
  userId: number;
  requestId?: string;
  surface?: string;
  onVoted?: () => void;
}

type VoteDirection = "upvote" | "downvote";

export default function VoteActions({
  newsId,
  userId,
  requestId,
  surface = "feed",
  onVoted,
}: Props) {
  const [selected, setSelected] = useState<VoteDirection | null>(null);

  const handleVote = (direction: VoteDirection) => {
    setSelected(direction);
    void trackEvent({
      user_id: userId,
      event_type: direction,
      surface,
      news_id: newsId,
      request_id: requestId ?? null,
    }).then(() => onVoted?.());
  };

  return (
    <div className="zr-vote-actions" aria-label="文章反馈">
      <button
        type="button"
        className={`zr-vote-btn${selected === "upvote" ? " zr-vote-btn--active" : ""}`}
        aria-label="赞同"
        aria-pressed={selected === "upvote"}
        onClick={() => handleVote("upvote")}
      >
        <ArrowUp size={16} />
      </button>
      <span className="zr-vote-divider" aria-hidden="true" />
      <button
        type="button"
        className={`zr-vote-btn${selected === "downvote" ? " zr-vote-btn--active" : ""}`}
        aria-label="不赞同"
        aria-pressed={selected === "downvote"}
        onClick={() => handleVote("downvote")}
      >
        <ArrowDown size={16} />
      </button>
    </div>
  );
}
