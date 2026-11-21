import type { AssetRead, MediaItemRead, ThemeSearchResult } from "../../generated/rest/types.gen";

export interface ThemeResultBadge {
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

export function extractYouTubeId(value: string): string | null {
  return value.match(/(?:v=|youtu\.be\/|shorts\/)([a-zA-Z0-9_-]{11})/)?.[1] ?? null;
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

  // 1. Currently selected video first (if any)
  if (theme?.youtube_id?.trim()) {
    const currentId = theme.youtube_id.trim();
    const title = theme.youtube_title?.trim() || (subject ? `${subject} Theme` : "Current theme");
    addOrUpdateBadge(
      currentId,
      { label: "Currently selected", variant: "success" },
      title,
      theme.youtube_duration ?? null,
    );
  }

  // 2. OvertureDB selection (if any)
  if (overtureDbId?.trim()) {
    const ovtId = overtureDbId.trim();
    const title = subject ? `${subject} Theme` : "OvertureDB theme";
    addOrUpdateBadge(ovtId, { label: "OvertureDB", variant: "accent" }, title);
  }

  // 3. ThemerrDB public selection (if any)
  if (themerrDbId?.trim()) {
    const thmId = themerrDbId.trim();
    const title = subject ? `${subject} Theme` : "ThemerrDB theme";
    addOrUpdateBadge(thmId, { label: "ThemerrDB", variant: "warning" }, title);
  }

  // 4. YouTube search results
  for (const result of searchResults) {
    if (!result?.id) continue;
    const existing = byId.get(result.id);
    if (existing) {
      if (result.title) {
        existing.title = result.title;
      }
      if (result.channel) {
        existing.channel = result.channel;
      }
      if (result.duration !== null && result.duration !== undefined) {
        existing.duration = result.duration;
      }
      if (result.thumbnail) {
        existing.thumbnail = result.thumbnail;
      }
      if (result.url) {
        existing.url = result.url;
      }
    } else {
      const item: ThemeSearchResultItem = {
        ...result,
        badges: [],
      };
      byId.set(result.id, item);
      list.push(item);
    }
  }

  return list;
}
