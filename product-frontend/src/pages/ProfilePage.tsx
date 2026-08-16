import ProfilePanel from "../components/ProfilePanel";
import { usePersona } from "../context/PersonaContext";

export default function ProfilePage() {
  const { refreshTick, bumpProfile } = usePersona();

  return (
    <main className="zr-center zr-profile-page">
      <header className="zr-page-header zr-profile-page__header">
        <span className="zr-eyebrow">你的阅读偏好</span>
        <h1>兴趣画像</h1>
        <p>查看推荐系统如何理解你的短期关注、长期兴趣和减少推荐主题。</p>
      </header>
      <ProfilePanel refreshTick={refreshTick} onReset={bumpProfile} variant="page" />
    </main>
  );
}
