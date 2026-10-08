import { request } from "../api/client";
import type { FeedResponse, LiveLanguage, NewsSpace, SearchResponse } from "../api/types";

export interface ReadingState { source_space: NewsSpace; article_id: string; saved: boolean; read: boolean }
export interface LibraryItem extends ReadingState { title: string; url: string; source_domain: string; available: boolean }
export interface PreferenceRule {
  id: number; source_space: NewsSpace; target_type: "source" | "topic" | "keyword";
  value: string; effect: "prefer" | "reduce" | "block"; enabled: boolean;
}
export interface SavedSearch { id: number; source_space: NewsSpace; query: string; language: LiveLanguage; category: string | null }
const post = <T,>(path: string, body: unknown) => request<T>(path, { method: "POST", body: JSON.stringify(body) });

export const getReadingStates = (space: NewsSpace, ids: string[]) => request<{ items: ReadingState[] }>("/reading/states", { params: { source_space: space, article_ids: ids.join(",") } });
export const updateReadingState = (space: NewsSpace, articleId: string, change: Partial<Pick<ReadingState, "saved" | "read">>) => post<ReadingState>("/reading/state", { source_space: space, article_id: articleId, ...change });
export const getLibrary = (space: NewsSpace, unreadOnly: boolean, offset = 0) => request<{ items: LibraryItem[]; has_more: boolean }>("/reading/library", { params: { source_space: space, saved_only: true, unread_only: unreadOnly, offset, limit: 20 } });
export const getRules = (space: NewsSpace) => request<{ items: PreferenceRule[] }>("/reading/rules", { params: { source_space: space } });
export const saveRule = (rule: Omit<PreferenceRule, "id"> & { id?: number }) => post<PreferenceRule>("/reading/rules", rule);
export const deleteRule = (space: NewsSpace, id: number) => post<void>(`/reading/rules/${id}/delete`, { source_space: space });
export const getSavedSearches = (space: NewsSpace) => request<{ items: SavedSearch[] }>("/reading/searches", { params: { source_space: space } });
export const saveSearch = (search: Omit<SavedSearch, "id">) => post<SavedSearch>("/reading/searches", search);
export const deleteSavedSearch = (space: NewsSpace, id: number) => post<void>(`/reading/searches/${id}/delete`, { source_space: space });
export const getReadingFeed = (space: NewsSpace, requestId: string, cursor: string | undefined, category: string | undefined, language: LiveLanguage, unreadOnly: boolean) => request<FeedResponse>("/reading/feed", { params: { source_space: space, request_id: requestId, cursor, category, language, unread_only: unreadOnly, page_size: 20 } });
export const searchReading = (space: NewsSpace, query: string, language: LiveLanguage, category: string | null, includeHidden: boolean, eventId: string) => post<SearchResponse & { hidden_count: number }>("/reading/search", { source_space: space, query, language, category, include_hidden: includeHidden, page_size: 20, event_id: eventId });
