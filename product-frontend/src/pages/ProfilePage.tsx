import ProfilePanel from "../components/ProfilePanel";
import { usePersona } from "../context/PersonaContext";
import { useSourceSpace } from "../context/SourceSpaceContext";

export default function ProfilePage() {
  const { selectedPersona, refreshTick, bumpProfile } = usePersona();
  const { sourceSpace } = useSourceSpace();

  return (
    <main className="zr-center zr-profile-page">
      <header className="zr-page-header zr-profile-page__header">
        <span className="zr-eyebrow">你的阅读偏好</span>
        <h1>兴趣画像</h1>
        <p>
          当前为{sourceSpace === "mind" ? " MIND" : "实时新闻"}空间；两个空间的兴趣画像互不共享。
        </p>
      </header>
      {selectedPersona ? (
        <ProfilePanel
          sourceSpace={sourceSpace}
          userId={selectedPersona.user_id}
          refreshTick={refreshTick}
          onReset={bumpProfile}
          variant="page"
        />
      ) : (
        <div className="zr-status">请选择一个用户画像。</div>
      )}
    </main>
  );
}
