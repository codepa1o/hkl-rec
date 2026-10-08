import { useEffect, useState, type FormEvent } from "react";
import { deleteRule, getRules, saveRule, type PreferenceRule } from "./api";
import { useReading } from "./ReadingContext";

const typeNames = { source: "来源域名", topic: "主题", keyword: "标题关键词" };
const effectNames = { prefer: "优先推荐", reduce: "减少推荐", block: "强制屏蔽" };
export default function PreferenceRules() {
  const reading = useReading();
  const [rules, setRules] = useState<PreferenceRule[]>([]);
  const [targetType, setTargetType] = useState<PreferenceRule["target_type"]>("keyword");
  const [effect, setEffect] = useState<PreferenceRule["effect"]>("prefer");
  const [value, setValue] = useState("");
  const [editing, setEditing] = useState<number>();
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    if (!reading?.active) return;
    let cancelled = false;
    getRules(reading.sourceSpace).then((response) => { if (!cancelled) setRules(response.items); }).catch((err: Error) => { if (!cancelled) setError(err.message); });
    return () => { cancelled = true; };
  }, [reading?.active, reading?.sourceSpace, refresh]);
  if (!reading?.active) return null;
  const mutate = async (action: () => Promise<unknown>) => {
    setPending(true); setError(null);
    try { await action(); reading.preferencesChanged(); setRefresh((n) => n + 1); return true; }
    catch (err) { setError(err instanceof Error ? err.message : "规则保存失败"); return false; }
    finally { setPending(false); }
  };
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (await mutate(() => saveRule({ id: editing, source_space: reading.sourceSpace, target_type: targetType, value: value.trim(), effect, enabled: true }))) { setValue(""); setEditing(undefined); }
  };
  return <section className="zr-reading-panel" aria-labelledby="reading-rules-title">
    <h2 id="reading-rules-title">我设置的偏好</h2>
    <p>手动规则独立于系统学习的兴趣。屏蔽优先于推荐，暂停或删除即可恢复。</p>
    <form className="zr-reading-form" onSubmit={(event) => void submit(event)}>
      <label>规则类型<select value={targetType} onChange={(e) => setTargetType(e.target.value as PreferenceRule["target_type"])}>{Object.entries(typeNames).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
      <label>匹配内容<input required maxLength={200} value={value} onChange={(e) => setValue(e.target.value)} placeholder={targetType === "source" ? "例如 theguardian.com" : targetType === "topic" ? "例如 科技" : "例如 人工智能"} /></label>
      <label>处理方式<select value={effect} onChange={(e) => setEffect(e.target.value as PreferenceRule["effect"])}>{Object.entries(effectNames).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
      <button type="submit" disabled={pending || !value.trim()}>{editing ? "保存修改" : "添加规则"}</button>
      {editing && <button type="button" onClick={() => { setEditing(undefined); setValue(""); }}>取消编辑</button>}
    </form>
    {error && <p role="alert">{error}<button type="button" onClick={() => { setError(null); setRefresh((n) => n + 1); }}>重新加载</button></p>}
    {rules.length === 0 && !error && <p>尚未设置规则。可以先关注一个主题，或减少不感兴趣的内容。</p>}
    <ul className="zr-reading-list">{rules.map((rule) => <li key={rule.id}>
      <div><strong>{rule.value}</strong><span>{typeNames[rule.target_type]} · {effectNames[rule.effect]} · {rule.enabled ? "生效中" : "已暂停"}</span></div>
      <div className="zr-reading-actions">
        <button disabled={pending} type="button" onClick={() => { setEditing(rule.id); setTargetType(rule.target_type); setValue(rule.value); setEffect(rule.effect); }}>编辑</button>
        <button disabled={pending} type="button" aria-label={rule.enabled ? "暂停规则" : "启用规则"} onClick={() => void mutate(() => saveRule({ ...rule, enabled: !rule.enabled }))}>{rule.enabled ? "暂停" : "启用"}</button>
        <button disabled={pending} type="button" onClick={() => void mutate(() => deleteRule(reading.sourceSpace, rule.id))}>删除</button>
      </div>
    </li>)}</ul>
  </section>;
}
