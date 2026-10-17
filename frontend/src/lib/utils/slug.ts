/**
 * Shared "id-title" URL slug helpers.
 *
 * Routes identify items and collections with a slug of the form
 * `{id}-{slugified-title}` (e.g. `42-the-matrix`) instead of a bare numeric
 * or opaque id, so links are both stable (the id drives lookups) and
 * readable/shareable. Both item ids (numeric DB primary keys) and Plex
 * collection ids (numeric ratingKeys) are digit-only in this app, so the
 * id can always be recovered by reading the leading digits back off the
 * slug.
 */

/** Lowercase, hyphenate, and strip a title down to URL-safe characters. */
export function slugify(title: string): string {
  return title
    .toLowerCase()
    .replace(/['\u2019]/g, "")
    .replace(/[^a-z0-9\s-]/g, "")
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-|-$/g, "");
}

/** Build an `{id}-{title}` slug for a route param. Falls back to a bare id if the title can't be slugified. */
export function buildIdSlug(id: number | string, title: string): string {
  const slug = slugify(title);
  return slug ? `${id}-${slug}` : String(id);
}

/** Where an item slug points: a stored item, or a TMDB title not yet stored. */
export type ItemSlug = { kind: "item"; id: number } | { kind: "tmdb"; tmdbId: number };

/**
 * Read an item route's slug: `{id}-{title}` for a stored item, or
 * `tmdb-{tmdbId}-{title}` for a TMDB title that is stored by its first
 * selection. A stored item's slug always starts with a digit, so the two
 * never collide.
 */
export function parseItemSlug(slug: string | undefined): ItemSlug | null {
  const match = /^(tmdb-)?(\d+)/.exec(slug ?? "");
  if (!match?.[2]) return null;
  const id = Number(match[2]);
  return match[1] ? { kind: "tmdb", tmdbId: id } : { kind: "item", id };
}

/** Recover the leading numeric id from an `{id}-{title}` slug. */
export function parseIdFromSlug(slug: string | undefined): string {
  if (!slug) return "";
  const match = /^(\d+)/.exec(slug);
  return match?.[1] ?? slug;
}
