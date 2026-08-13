import { usePersona } from "../context/PersonaContext";
import ProfileDebugPanel from "./ProfileDebugPanel";

export default function RightRail() {
  const { selectedPersona, refreshTick } = usePersona();

  return (
    <aside className="zr-right" id="your-interests" aria-label="兴趣画像">
      {selectedPersona ? (
        <ProfileDebugPanel userId={selectedPersona.user_id} refreshTick={refreshTick} />
      ) : (
        <div className="zr-rail-card zr-status">选择用户画像后，这里会展示你的兴趣。</div>
      )}
    </aside>
  );
}
