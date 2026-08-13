import { ChevronDown, User } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { usePersona } from "../context/PersonaContext";
import { localizePersonaName } from "../localization";

export default function PersonaSwitcher() {
  const { personas, selectedPersona, selectPersona, loading } = usePersona();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onClick);
    return () => document.removeEventListener("mousedown", onClick);
  }, []);

  if (loading || personas.length === 0) {
    return (
      <div className="zr-persona-switcher">
        <User size={20} />
        <span style={{ color: "var(--zr-text-muted)" }}>加载中…</span>
      </div>
    );
  }

  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button className="zr-persona-switcher" onClick={() => setOpen((v) => !v)}>
        <span
          className="zr-persona-switcher__avatar"
          style={{
            background: `linear-gradient(135deg, hsl(${(selectedPersona?.user_id ?? 1) * 47 % 360}, 60%, 55%), hsl(${(selectedPersona?.user_id ?? 1) * 83 % 360}, 70%, 65%))`,
          }}
        />
        <span>{localizePersonaName(selectedPersona?.display_name)}</span>
        <ChevronDown size={14} />
      </button>

      {open && (
        <div className="zr-persona-menu">
          {personas.map((p) => (
            <button
              key={p.user_id}
              className={`zr-persona-menu__item${p.user_id === selectedPersona?.user_id ? " zr-persona-menu__item--active" : ""}`}
              onClick={() => {
                selectPersona(p.user_id);
                setOpen(false);
              }}
            >
              <span
                className="zr-persona-switcher__avatar"
                style={{
                  background: `linear-gradient(135deg, hsl(${p.user_id * 47 % 360}, 60%, 55%), hsl(${p.user_id * 83 % 360}, 70%, 65%))`,
                }}
              />
              <span>{localizePersonaName(p.display_name)}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
