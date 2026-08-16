import { Search, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { listSearchSuggestions } from "../api/client";
import type { SuggestionItem } from "../api/types";
import { localizeCategoryName } from "../localization";

interface Props {
  initialQuery?: string;
}

export default function SearchBox({ initialQuery }: Props) {
  const [query, setQuery] = useState(initialQuery ?? "");
  const [suggestions, setSuggestions] = useState<SuggestionItem[]>([]);
  const [open, setOpen] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout>>();
  const wrapRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();
  const location = useLocation();
  const canSearch = query.trim().length > 0;

  useEffect(() => {
    setQuery(initialQuery ?? "");
  }, [initialQuery]);

  useEffect(() => {
    function onDocClick(e: MouseEvent) {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, []);

  const fetchSuggestions = useCallback((q: string) => {
    if (q.length < 1) {
      setSuggestions([]);
      return;
    }
    listSearchSuggestions(8).then((res) => {
      const filtered = res.items.filter(
        (s) =>
          s.label.toLowerCase().includes(q.toLowerCase()) ||
          s.query_key.toLowerCase().includes(q.toLowerCase()),
      );
      setSuggestions(filtered.slice(0, 8));
    });
  }, []);

  const handleChange = (value: string) => {
    setQuery(value);
    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => fetchSuggestions(value), 200);
    setOpen(true);
  };

  const handleSubmit = (suggestionKey?: string) => {
    if (suggestionKey) {
      setOpen(false);
      navigate(`/search?q=${encodeURIComponent(suggestionKey)}&exact=1`);
      return;
    }
    const text = query.trim();
    if (!text) return;
    setOpen(false);
    navigate(`/search?q=${encodeURIComponent(text)}`);
  };

  const handleClear = () => {
    clearTimeout(debounceRef.current);
    setQuery("");
    setSuggestions([]);
    setOpen(false);
    if (location.pathname === "/search") {
      navigate("/search", { replace: true });
    }
    inputRef.current?.focus();
  };

  return (
    <div className="zr-searchbox" ref={wrapRef}>
      <div className="zr-searchbox__input-wrap">
        <Search className="zr-searchbox__leading-icon" size={18} aria-hidden="true" />
        <input
          ref={inputRef}
          className="zr-searchbox__input"
          aria-label="搜索新闻"
          placeholder="搜索新闻"
          value={query}
          onChange={(e) => handleChange(e.target.value)}
          onFocus={() => setOpen(true)}
          onKeyDown={(e) => {
            if (e.key === "Enter") handleSubmit();
          }}
        />
        {query.length > 0 && (
          <button
            type="button"
            className="zr-searchbox__clear"
            aria-label="清空搜索内容"
            title="清空搜索内容"
            onClick={handleClear}
          >
            <X size={17} aria-hidden="true" />
          </button>
        )}
        <button
          type="button"
          className="zr-searchbox__submit"
          disabled={!canSearch}
          onClick={() => handleSubmit()}
        >
          搜索
        </button>
      </div>

      {open && suggestions.length > 0 && (
        <div className="zr-searchbox__suggestions">
          {suggestions.map((s) => (
            <button
              key={s.query_key}
              className="zr-searchbox__suggestion"
              onClick={() => handleSubmit(s.query_key)}
            >
              <span>{localizeCategoryName(s.label)}</span>
              <span className="zr-searchbox__suggestion-key">{s.topic_count} 个主题</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
