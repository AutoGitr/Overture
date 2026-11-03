import type { CatalogMediaType, MediaItemRead } from "../../generated/rest/types.gen";
import { slugify } from "./slug";

export function buildTmdbCollectionUrl(id: number): string {
  return `https://www.themoviedb.org/collection/${id}`;
}

/** What the detail view shows: a stored item, or a TMDB title not yet stored. */
export type DetailSubject = Pick<
  MediaItemRead,
  "title" | "year" | "tmdb_id" | "tvdb_id" | "imdb_id"
> & { media_type: CatalogMediaType };

type DetailMode = "art" | "themes" | string;

export function buildTmdbUrl(
  item: DetailSubject | null,
  mode: DetailMode,
  artType: string,
  season: { season_num: number } | null,
) {
  if (!item?.tmdb_id) return null;
  const base =
    item.media_type === "collection"
      ? buildTmdbCollectionUrl(item.tmdb_id)
      : `https://www.themoviedb.org/${item.media_type === "movie" ? "movie" : "tv"}/${item.tmdb_id}`;
  if (mode !== "art") return base;
  if (artType === "poster") return `${base}/images/posters`;
  if (artType === "background") return `${base}/images/backdrops`;
  if (item.media_type === "show" && artType === "season_poster" && season) {
    return `${base}/season/${season.season_num}/images/posters`;
  }
  return base;
}

export function buildTvdbUrl(item: DetailSubject | null) {
  if (!item?.tvdb_id || !item.title || item.media_type === "collection") return null;
  return `https://thetvdb.com/${item.media_type === "movie" ? "movies" : "series"}/${slugify(item.title)}`;
}

export function buildPosterDbUrl(item: DetailSubject | null) {
  if (!item?.title) return null;
  const term = encodeURIComponent(item.title).replace(/%20/g, "+");
  const section =
    item.media_type === "collection"
      ? "collections"
      : item.media_type === "movie"
        ? "movies"
        : "shows";
  return `https://theposterdb.com/search?term=${term}&section=${section}`;
}

export function buildImdbUrl(imdbId: string) {
  return `https://www.imdb.com/title/${encodeURIComponent(imdbId)}/`;
}
