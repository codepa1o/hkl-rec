import { useAuth } from "../context/AuthContext";
import { usePersona } from "../context/PersonaContext";
import ProfileDebugPanel from "./ProfileDebugPanel";
import ProfilePanel from "./ProfilePanel";

export default function RightRail() {
  const { user } = useAuth();
  const { selectedPersona, refreshTick, bumpProfile } = usePersona();
  const isCurrentUser = Boolean(
    user && selectedPersona && user.user_id === selectedPersona.user_id,
  );

  return (
    <aside className="zr-right" id="your-interests" aria-label="兴趣画像">
      {isCurrentUser ? (
        <ProfilePanel refreshTick={refreshTick} onReset={bumpProfile} />
      ) : selectedPersona ? (
        <ProfileDebugPanel userId={selectedPersona.user_id} refreshTick={refreshTick} />
      ) : (
        <div className="zr-rail-card zr-status">选择用户画像后，这里会展示你的兴趣。</div>
      )}
    </aside>
  );
}
