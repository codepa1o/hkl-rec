import type {
  ArticleCardResponse,
  AuthUser,
  CategoryListResponse,
  DebugProfileResponse,
  EventTrackRequest,
  EventTrackResponse,
  FeedResponse,
  PersonaListResponse,
  ProfileResponse,
  LoginInput,
  LiveLanguage,
  NewsSpace,
  NewsSpaceListResponse,
  RegisterInput,
  SearchResponse,
  SuggestionListResponse,
} from "./types";

const BASE_URL: string =
  (import.meta.env.VITE_NEWSREC_API_BASE as string | undefined)?.trim() ||
  `${globalThis.location?.protocol ?? "http:"}//${globalThis.location?.hostname || "127.0.0.1"}:8000`;

export const UNAUTHORIZED_EVENT = "newsrec:unauthorized";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export function newClientId(prefix: string): string {
  const randomPart =
    globalThis.crypto?.randomUUID?.() ??
    `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  return `${prefix}-${randomPart}`;
}

const stableClientIds = new Map<string, string>();

export function stableClientId(prefix: string, logicalKey: string): string {
  const cacheKey = `${prefix}:${logicalKey}`;
  const existing = stableClientIds.get(cacheKey);
  if (existing) return existing;
  const created = newClientId(prefix);
  stableClientIds.set(cacheKey, created);
  return created;
}

async function request<T>(
  path: string,
  init?: RequestInit & { params?: Record<string, string | number | boolean | undefined> },
): Promise<T> {
  const url = new URL(path, BASE_URL);
  if (init?.params) {
    for (const [key, value] of Object.entries(init.params)) {
      if (value === undefined || value === null) continue;
      url.searchParams.set(key, String(value));
    }
  }
  const { params: _params, ...rest } = init ?? {};
  const response = await fetch(url.toString(), {
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    ...rest,
  });
  if (!response.ok) {
    const body = (await response.json().catch(() => null)) as { detail?: string } | null;
    if (response.status === 401) globalThis.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
    throw new ApiError(body?.detail || `请求失败（${response.status}）`, response.status);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function register(payload: RegisterInput): Promise<AuthUser> {
  return request<AuthUser>("/auth/register", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function login(payload: LoginInput): Promise<AuthUser> {
  return request<AuthUser>("/auth/login", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function getCurrentUser(): Promise<AuthUser> {
  return request<AuthUser>("/auth/me");
}

export function logout(): Promise<void> {
  return request<void>("/auth/logout", { method: "POST" });
}

export function listNewsSpaces(): Promise<NewsSpaceListResponse> {
  return request<NewsSpaceListResponse>("/news-spaces");
}

export function listPersonas(limit = 10, sourceSpace: NewsSpace = "mind"): Promise<PersonaListResponse> {
  return request<PersonaListResponse>("/personas", {
    params: { limit, source_space: sourceSpace },
  });
}

export function listCategories(sourceSpace: NewsSpace = "mind"): Promise<CategoryListResponse> {
  return request<CategoryListResponse>("/categories", {
    params: { source_space: sourceSpace },
  });
}

export function listSearchSuggestions(
  limit = 12,
  sourceSpace: NewsSpace = "mind",
): Promise<SuggestionListResponse> {
  return request<SuggestionListResponse>("/search/suggestions", {
    params: { limit, source_space: sourceSpace },
  });
}

export function getFeed(
  userId: number,
  pageSize = 10,
  debug = false,
  requestId?: string,
  cursor?: string,
  category?: string,
  sourceSpace: NewsSpace = "mind",
  language: LiveLanguage = "all",
): Promise<FeedResponse> {
  return request<FeedResponse>("/feed", {
    params: {
      user_id: userId,
      page_size: pageSize,
      debug,
      request_id: requestId,
      cursor,
      category,
      source_space: sourceSpace,
      language,
    },
  });
}

export interface SearchInput {
  queryText?: string;
  queryKey?: string;
}

export function postSearch(
  userId: number,
  input: SearchInput,
  pageSize = 10,
  eventId?: string,
  sourceSpace: NewsSpace = "mind",
): Promise<SearchResponse> {
  return request<SearchResponse>("/search", {
    method: "POST",
    body: JSON.stringify({
      user_id: userId,
      event_id: eventId,
      query_text: input.queryText,
      query_key: input.queryKey,
      page_size: pageSize,
      source_space: sourceSpace,
    }),
  });
}

export function getArticleCard(
  articleId: string,
  sourceSpace: NewsSpace = "mind",
): Promise<ArticleCardResponse> {
  return request<ArticleCardResponse>(`/articles/${sourceSpace}/${articleId}`);
}

export function getDebugProfile(
  userId: number,
  sourceSpace: NewsSpace = "mind",
): Promise<DebugProfileResponse> {
  return request<DebugProfileResponse>("/debug/profile", {
    params: { user_id: userId, source_space: sourceSpace },
  });
}

export function getProfile(sourceSpace: NewsSpace, userId: number): Promise<ProfileResponse> {
  return request<ProfileResponse>("/profile", {
    params: { source_space: sourceSpace, user_id: userId },
  });
}

export function resetProfile(sourceSpace: NewsSpace, userId: number): Promise<ProfileResponse> {
  return request<ProfileResponse>("/profile/reset", {
    method: "POST",
    body: JSON.stringify({ source_space: sourceSpace, user_id: userId }),
  });
}

export function trackEvent(payload: EventTrackRequest): Promise<EventTrackResponse> {
  return request<EventTrackResponse>("/event/track", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function sendTrackedEventKeepalive(payload: EventTrackRequest): void {
  const url = new URL("/event/track", BASE_URL);
  const beaconUrl = new URL("/event/track/beacon", BASE_URL);
  const serialized = JSON.stringify(payload);
  let acceptedByBeacon = false;
  try {
    acceptedByBeacon = Boolean(
      globalThis.navigator?.sendBeacon?.(
        beaconUrl.toString(),
        serialized,
      ),
    );
  } catch {
    acceptedByBeacon = false;
  }
  if (acceptedByBeacon) return;
  void fetch(url.toString(), {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: serialized,
    keepalive: true,
  }).catch(() => undefined);
}
