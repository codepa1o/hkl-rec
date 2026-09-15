const CATEGORY_LABELS: Record<string, string> = {
  "live-world": "国际",
  "live-politics": "政治",
  "live-business": "财经",
  "live-technology": "科技",
  "live-science": "科学",
  "live-health": "健康",
  "live-society-law": "社会与法治",
  "live-education": "教育",
  "live-environment": "环境与气候",
  "live-culture": "文化艺术",
  "live-entertainment": "娱乐",
  "live-sports": "体育",
  "live-lifestyle": "生活方式",
  "live-general": "综合",
  news: "新闻",
  sports: "体育",
  football: "足球",
  finance: "财经",
  science: "科学",
  technology: "科技",
  tech: "科技",
  autos: "汽车",
  automotive: "汽车",
  entertainment: "娱乐",
  movies: "电影",
  tv: "电视",
  music: "音乐",
  health: "健康",
  travel: "旅行",
  weather: "天气",
  lifestyle: "生活方式",
  "food and drink": "美食与饮品",
  foodanddrink: "美食与饮品",
  video: "视频",
  kids: "儿童",
  education: "教育",
  politics: "政治",
  business: "商业",
  markets: "市场",
  world: "国际",
  "north america": "北美",
  northamerica: "北美",
  "middle east": "中东",
  middleeast: "中东",
  gaming: "游戏",
  games: "游戏",
  sponsored: "赞助内容",
  "sponsored content": "赞助内容",
};

const PERSONA_SUFFIXES: Record<string, string> = {
  reader: "读者",
  explorer: "探索者",
};

const RECOMMENDATION_REASONS: Record<string, string> = {
  "filled by hot_or_fresh because primary recall was short.":
    "主要召回结果不足，已用热门或新鲜内容补充。",
  "selected because recent query categories boosted this article.":
    "近期搜索的相关分类提升了这篇文章的推荐优先级。",
  "selected because its categories match the user profile.":
    "文章分类与当前用户画像相匹配。",
  "selected by base recall score.": "根据基础召回得分推荐。",
};

function normalized(value: string): string {
  return value.trim().toLowerCase().replace(/[_-]+/g, " ").replace(/\s+/g, " ");
}

export function localizeCategoryName(value?: string | null): string {
  if (!value) return "新闻";
  return CATEGORY_LABELS[value.trim().toLowerCase()] ?? CATEGORY_LABELS[normalized(value)] ?? value;
}

export function localizePersonaName(value?: string | null): string {
  if (!value) return "选择用户画像";
  const match = value.trim().match(/^(.+?)\s+(Reader|Explorer)$/i);
  if (!match) return value;

  const category = localizeCategoryName(match[1]);
  const suffix = PERSONA_SUFFIXES[match[2].toLowerCase()];
  if (category === match[1] || !suffix) return value;
  return `${category}${suffix}`;
}

export function localizeRecommendationReason(value: string): string {
  const exact = RECOMMENDATION_REASONS[value.trim().toLowerCase()];
  if (exact) return exact;

  const sponsored = value.match(
    /^Sponsored candidate from (.+?); eligible by topic, budget, pacing, and frequency cap\.$/i,
  );
  if (sponsored) {
    return `来自“${sponsored[1]}”活动的赞助推荐，已通过主题、预算、投放节奏和频次限制检查。`;
  }
  return value;
}

export function localizeInterfaceError(value?: string | null): string {
  if (!value) return "发生未知错误，请稍后重试。";
  const status = value.match(/^([45]\d{2})\b/)?.[1];
  if (status === "404") return "未找到请求的内容。";
  if (status === "422") return "请求内容无法处理，请检查后重试。";
  if (status === "429") return "操作过于频繁，请稍后重试。";
  if (status && Number(status) >= 500) return "服务暂时不可用，请稍后重试。";
  return "请求失败，请稍后重试。";
}

export function localizeProfileSeedName(value?: string | null): string {
  if (!value) return "未设置";
  const labels: Record<string, string> = {
    cold_start_default: "默认冷启动",
    evaluation_empty: "评测空画像",
  };
  return labels[value.trim().toLowerCase()] ?? value;
}
