import type { AssetRead, MediaItemRead, ThemeSearchResult } from "../../generated/rest/types.gen";
import { YOUTUBE_ID_PATTERN } from "../../generated/settings";

const YOUTUBE_ID = new RegExp(YOUTUBE_ID_PATTERN);

interface ThemeResultBadge {
  label: string;
  variant?: "success" | "accent" | "warning" | "danger" | "muted" | string;
}

export interface ThemeSearchResultItem extends ThemeSearchResult {
  badges?: ThemeResultBadge[];
}

export function buildThemeSearchQuery(
  item: Pick<MediaItemRead, "title" | "year">,
  format: string,
): string {
  const template = format || "{title} theme";
  return template
    .replace(/\{title\}/gi, item.title || "")
    .replace(/\{year\}/gi, String(item.year || ""))
    .trim();
}

/** What a collection's theme is searched for; collections have no year. */
export function buildCollectionThemeSearchQuery(title: string): string {
  return `${title} main theme music ost`;
}

export function youtubeSearchUrl(query: string): string {
  return `https://www.youtube.com/results?search_query=${encodeURIComponent(query)}`;
}

export function formatThemeDuration(seconds: number | null | undefined): string {
  if (!seconds || seconds < 0) return "";
  const wholeSeconds = Math.floor(seconds);
  const minutes = Math.floor(wholeSeconds / 60);
  const remainder = wholeSeconds % 60;
  return `${minutes}:${remainder.toString().padStart(2, "0")}`;
}

export function youtubeEmbedUrl(videoId: string): string {
  return `https://www.youtube-nocookie.com/embed/${encodeURIComponent(videoId)}`;
}

export function youtubeShortUrl(videoId: string): string {
  return `https://youtu.be/${encodeURIComponent(videoId)}`;
}

export function isYouTubeUrl(value: string): boolean {
  return /(?:youtube\.com\/watch|youtu\.be\/|youtube\.com\/shorts\/)/.test(value);
}

/** The video ID a link names, when it is one the catalog contract accepts. */
export function extractYouTubeId(value: string): string | null {
  const candidate = value.match(/(?:v=|youtu\.be\/|shorts\/)([^&?#/\s]+)/)?.[1];
  return candidate !== undefined && YOUTUBE_ID.test(candidate) ? candidate : null;
}

/** Return unique non-empty YouTube IDs in order, trimming surrounding whitespace. */
export function themeCandidateVideoIds(...ids: (string | null | undefined)[]): string[] {
  const unique: string[] = [];
  const seen = new Set<string>();
  for (const raw of ids) {
    const id = raw?.trim();
    if (id && !seen.has(id)) {
      seen.add(id);
      unique.push(id);
    }
  }
  return unique;
}

export interface MergeThemeResultsParams {
  /** The title or collection the theme is for. */
  title: string | null;
  /** Its theme asset, when one is stored. */
  theme: Pick<AssetRead, "youtube_id" | "youtube_title" | "youtube_duration"> | null;
  overtureDbId?: string | null;
  themerrDbId?: string | null;
  searchResults?: ThemeSearchResult[];
}

/** A search result's fields that say something, which replace a pick's guesses. */
function knownFields(result: ThemeSearchResult): Partial<ThemeSearchResultItem> {
  const fields: Partial<ThemeSearchResultItem> = {};
  if (result.title) fields.title = result.title;
  if (result.channel) fields.channel = result.channel;
  if (result.duration != null) fields.duration = result.duration;
  if (result.thumbnail) fields.thumbnail = result.thumbnail;
  if (result.url) fields.url = result.url;
  return fields;
}

export function mergeThemeResults({
  title: subject,
  theme,
  overtureDbId,
  themerrDbId,
  searchResults = [],
}: MergeThemeResultsParams): ThemeSearchResultItem[] {
  const list: ThemeSearchResultItem[] = [];
  const byId = new Map<string, ThemeSearchResultItem>();

  function addOrUpdateBadge(
    id: string,
    badge: ThemeResultBadge,
    defaultTitle: string,
    defaultDuration: number | null = null,
  ) {
    const existing = byId.get(id);
    if (existing) {
      const hasBadge = existing.badges?.some((b) => b.label === badge.label);
      if (!hasBadge) {
        existing.badges = [...(existing.badges || []), badge];
      }
    } else {
      const newItem: ThemeSearchResultItem = {
        id,
        title: defaultTitle,
        duration: defaultDuration,
        channel: null,
        thumbnail: null,
        url: youtubeShortUrl(id),
        badges: [badge],
      };
      byId.set(id, newItem);
      list.push(newItem);
    }
  }

  // The current theme first, then each database's pick, each once with every
  // badge that names it.
  const titled = (fallback: string) => (subject ? `${subject} Theme` : fallback);
  const picks = [
    {
      id: theme?.youtube_id,
      badge: { label: "Currently selected", variant: "success" },
      title: theme?.youtube_title?.trim() || titled("Current theme"),
      duration: theme?.youtube_duration ?? null,
    },
    {
      id: overtureDbId,
      badge: { label: "OvertureDB", variant: "accent" },
      title: titled("OvertureDB theme"),
      duration: null,
    },
    {
      id: themerrDbId,
      badge: { label: "ThemerrDB", variant: "warning" },
      title: titled("ThemerrDB theme"),
      duration: null,
    },
  ] satisfies {
    id: string | null | undefined;
    badge: ThemeResultBadge;
    title: string;
    duration: number | null;
  }[];
  for (const pick of picks) {
    const id = pick.id?.trim();
    if (id) addOrUpdateBadge(id, pick.badge, pick.title, pick.duration);
  }

  // YouTube's results, which fill in what a pick of the same video lacks.
  for (const result of searchResults) {
    if (!result?.id) continue;
    const existing = byId.get(result.id);
    if (existing) {
      Object.assign(existing, knownFields(result));
    } else {
      const item: ThemeSearchResultItem = { ...result, badges: [] };
      byId.set(result.id, item);
      list.push(item);
    }
  }

  return list;
}
