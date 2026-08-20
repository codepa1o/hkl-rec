import { useSourceSpace } from "../context/SourceSpaceContext";
import "./SourceSpaceSwitcher.css";

export default function SourceSpaceSwitcher() {
  const { sourceSpace, liveEnabled, loading, selectSourceSpace } = useSourceSpace();
  return (
    <div className="zr-source-switcher" aria-label="新闻来源">
      <button
        type="button"
        className="zr-source-switcher__option"
        aria-pressed={sourceSpace === "mind"}
        onClick={() => selectSourceSpace("mind")}
      >
        MIND 数据集
      </button>
      <button
        type="button"
        className="zr-source-switcher__option"
        aria-pressed={sourceSpace === "live"}
        disabled={loading || !liveEnabled}
        title={!loading && !liveEnabled ? "实时新闻暂未启用" : undefined}
        onClick={() => selectSourceSpace("live")}
      >
        实时新闻
      </button>
    </div>
  );
}
