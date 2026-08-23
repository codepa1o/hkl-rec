import type { FeedItem, LiveLanguage, NewsSpace } from "../api/types";

export const FEED_SESSION_STORAGE_KEY = "newsrec:feed-sessions:v1";
export const FEED_SESSION_SCHEMA_VERSION = 1 as const;
export const FEED_SESSION_TTL_MS = 2 * 60 * 60 * 1_000;
export const FEED_SESSION_MAX_CONTEXTS = 8;
export const FEED_SESSION_SOFT_LIMIT_BYTES = 3 * 1024 * 1024;

const PERSONA_SELECTION_PREFIX = "newsrec:feed-persona:v1:";

export interface FeedContextIdentity {
  sourceSpace: NewsSpace;
  personaUserId: number;
  category: string | null;
  language: LiveLanguage;
}

export interface FeedPageSnapshot {
  requestId: string;
  items: FeedItem[];
}

export interface FeedSessionSnapshot {
  schemaVersion: typeof FEED_SESSION_SCHEMA_VERSION;
  contextKey: string;
  sourceSpace: NewsSpace;
  personaUserId: number;
  category: string | null;
  language: LiveLanguage;
  pages: FeedPageSnapshot[];
  feedUserId: number;
  nextCursor: string | null;
  hasMore: boolean;
  anchorArticleId: string | null;
  anchorViewportTop: number | null;
  scrollY: number;
  feedWatermark: string | null;
  savedAt: number;
  lastAccessedAt: number;
}

interface FeedSessionEnvelope {
  schemaVersion: typeof FEED_SESSION_SCHEMA_VERSION;
  sessions: Record<string, FeedSessionSnapshot>;
}

interface StoreOptions {
  storage?: Storage;
  now?: () => number;
}

const defaultNow = () => Date.now();

function resolveStorage(options?: StoreOptions): Storage | null {
  if (options?.storage) return options.storage;
  try {
    return globalThis.sessionStorage;
  } catch {
    return null;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNewsSpace(value: unknown): value is NewsSpace {
  return value === "mind" || value === "live";
}

function isLanguage(value: unknown): value is LiveLanguage {
  return value === "all" || value === "zh" || value === "en";
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function isPositiveInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isInteger(value) && value > 0;
}

function isFeedItem(value: unknown, sourceSpace: NewsSpace): value is FeedItem {
  return (
    isRecord(value) &&
    value.source_space === sourceSpace &&
    typeof value.article_id === "string" &&
    typeof value.title === "string" &&
    typeof value.abstract === "string" &&
    typeof value.url === "string" &&
    typeof value.source_domain === "string" &&
    Array.isArray(value.categories)
  );
}

function isSnapshot(value: unknown, expectedKey?: string): value is FeedSessionSnapshot {
  if (!isRecord(value) || value.schemaVersion !== FEED_SESSION_SCHEMA_VERSION) return false;
  if (!isNewsSpace(value.sourceSpace) || !isLanguage(value.language)) return false;
  if (
    typeof value.contextKey !== "string" ||
    (expectedKey !== undefined && value.contextKey !== expectedKey) ||
    !isPositiveInteger(value.personaUserId) ||
    !(value.category === null || typeof value.category === "string") ||
    !isPositiveInteger(value.feedUserId) ||
    value.feedUserId !== value.personaUserId ||
    !isNullableString(value.nextCursor) ||
    typeof value.hasMore !== "boolean" ||
    !isNullableString(value.anchorArticleId) ||
    !(value.anchorViewportTop === null || isFiniteNumber(value.anchorViewportTop)) ||
    !isFiniteNumber(value.scrollY) ||
    !isNullableString(value.feedWatermark) ||
    !isFiniteNumber(value.savedAt) ||
    !isFiniteNumber(value.lastAccessedAt) ||
    !Array.isArray(value.pages)
  ) {
    return false;
  }
  const sourceSpace = value.sourceSpace;
  const canonicalKey = buildFeedContextKey({
    sourceSpace: value.sourceSpace,
    personaUserId: value.personaUserId,
    category: value.category,
    language: value.language,
  });
  if (canonicalKey !== value.contextKey) return false;
  return value.pages.every(
    (page) =>
      isRecord(page) &&
      typeof page.requestId === "string" &&
      Array.isArray(page.items) &&
      page.items.every((entry) => isFeedItem(entry, sourceSpace)),
  );
}

function emptyEnvelope(): FeedSessionEnvelope {
  return { schemaVersion: FEED_SESSION_SCHEMA_VERSION, sessions: {} };
}

function readEnvelope(storage: Storage): FeedSessionEnvelope {
  let raw: string | null;
  try {
    raw = storage.getItem(FEED_SESSION_STORAGE_KEY);
  } catch {
    return emptyEnvelope();
  }
  if (!raw) return emptyEnvelope();
  try {
    const parsed: unknown = JSON.parse(raw);
    if (
      !isRecord(parsed) ||
      parsed.schemaVersion !== FEED_SESSION_SCHEMA_VERSION ||
      !isRecord(parsed.sessions)
    ) {
      storage.removeItem(FEED_SESSION_STORAGE_KEY);
      return emptyEnvelope();
    }
    const sessions: Record<string, FeedSessionSnapshot> = {};
    let removedInvalid = false;
    Object.entries(parsed.sessions).forEach(([key, value]) => {
      if (isSnapshot(value, key)) sessions[key] = value;
      else removedInvalid = true;
    });
    const envelope: FeedSessionEnvelope = {
      schemaVersion: FEED_SESSION_SCHEMA_VERSION,
      sessions,
    };
    if (removedInvalid) writeEnvelope(storage, envelope);
    return envelope;
  } catch {
    try {
      storage.removeItem(FEED_SESSION_STORAGE_KEY);
    } catch {
      // Storage is optional; normal feed loading remains available.
    }
    return emptyEnvelope();
  }
}

function writeEnvelope(storage: Storage, envelope: FeedSessionEnvelope): boolean {
  try {
    storage.setItem(FEED_SESSION_STORAGE_KEY, JSON.stringify(envelope));
    return true;
  } catch {
    return false;
  }
}

function serializedBytes(value: unknown): number {
  return new TextEncoder().encode(JSON.stringify(value)).byteLength;
}

export function buildFeedContextKey(context: FeedContextIdentity): string {
  return JSON.stringify([
    context.sourceSpace,
    context.personaUserId,
    context.category ?? "",
    context.language,
  ]);
}

export function readFeedSnapshot(
  contextKey: string,
  options?: StoreOptions,
): FeedSessionSnapshot | null {
  const storage = resolveStorage(options);
  if (!storage) return null;
  const now = (options?.now ?? defaultNow)();
  const envelope = readEnvelope(storage);
  const value = envelope.sessions[contextKey];
  if (!value) return null;
  if (now - value.savedAt > FEED_SESSION_TTL_MS) {
    delete envelope.sessions[contextKey];
    writeEnvelope(storage, envelope);
    return null;
  }
  const accessed = { ...value, lastAccessedAt: now };
  envelope.sessions[contextKey] = accessed;
  writeEnvelope(storage, envelope);
  return accessed;
}

export function saveFeedSnapshot(
  snapshot: FeedSessionSnapshot,
  options?: StoreOptions,
): boolean {
  const storage = resolveStorage(options);
  if (!storage || !isSnapshot(snapshot, snapshot.contextKey)) return false;
  const now = (options?.now ?? defaultNow)();
  const envelope = readEnvelope(storage);
  envelope.sessions[snapshot.contextKey] = {
    ...snapshot,
    savedAt: now,
    lastAccessedAt: now,
  };

  const oldestFirst = () =>
    Object.values(envelope.sessions).sort(
      (left, right) => left.lastAccessedAt - right.lastAccessedAt,
    );
  while (Object.keys(envelope.sessions).length > FEED_SESSION_MAX_CONTEXTS) {
    const oldest = oldestFirst()[0];
    delete envelope.sessions[oldest.contextKey];
  }
  while (serializedBytes(envelope) > FEED_SESSION_SOFT_LIMIT_BYTES) {
    const oldestOther = oldestFirst().find(
      (entry) => entry.contextKey !== snapshot.contextKey,
    );
    if (!oldestOther) return false;
    delete envelope.sessions[oldestOther.contextKey];
  }
  return writeEnvelope(storage, envelope);
}

export function removeFeedSnapshot(contextKey: string, options?: StoreOptions): void {
  const storage = resolveStorage(options);
  if (!storage) return;
  const envelope = readEnvelope(storage);
  delete envelope.sessions[contextKey];
  writeEnvelope(storage, envelope);
}

export function personaSelectionKey(
  accountUserId: number | null,
  sourceSpace: NewsSpace,
): string {
  return `${PERSONA_SELECTION_PREFIX}${accountUserId ?? "demo"}:${sourceSpace}`;
}

export function readPersonaSelection(
  accountUserId: number | null,
  sourceSpace: NewsSpace,
  options?: StoreOptions,
): number | null {
  const storage = resolveStorage(options);
  if (!storage) return null;
  try {
    const value = Number(storage.getItem(personaSelectionKey(accountUserId, sourceSpace)));
    return Number.isInteger(value) && value > 0 ? value : null;
  } catch {
    return null;
  }
}

export function savePersonaSelection(
  accountUserId: number | null,
  sourceSpace: NewsSpace,
  personaUserId: number,
  options?: StoreOptions,
): boolean {
  const storage = resolveStorage(options);
  if (!storage || !Number.isInteger(personaUserId) || personaUserId <= 0) return false;
  try {
    storage.setItem(
      personaSelectionKey(accountUserId, sourceSpace),
      String(personaUserId),
    );
    return true;
  } catch {
    return false;
  }
}

export function clearFeedSessionData(options?: StoreOptions): void {
  const storage = resolveStorage(options);
  if (!storage) return;
  try {
    storage.removeItem(FEED_SESSION_STORAGE_KEY);
    for (let index = storage.length - 1; index >= 0; index -= 1) {
      const key = storage.key(index);
      if (key?.startsWith(PERSONA_SELECTION_PREFIX)) storage.removeItem(key);
    }
  } catch {
    // Authentication and navigation must not depend on browser storage.
  }
}
