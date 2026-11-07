import type {
  ArtCandidate,
  CollectionRead,
  MediaItemRead,
  ProxyCollectionImageData,
  SeasonRead,
} from "../../generated/rest/types.gen";
import {
  collectionProviderArtUrl,
  itemProviderArtUrl,
  localCollectionImageUrl,
  localItemImageUrl,
  localSeasonImageUrl,
  seasonProviderArtUrl,
} from "../rest/urls";

/** The rendition sized for the detail page; no size means the original image. */
type ImageSize = NonNullable<NonNullable<ProxyCollectionImageData["query"]>["size"]>;

/**
 * How a remote poster (TMDB, fanart.tv, TheTVDB) is shown: by its preview,
 * the size of an art grid card and of the detail poster, when its source has
 * one. A search result, its detail page and the stored item share it.
 */
export function remotePosterUrl(art: {
  poster_url?: string | null;
  poster_preview_url?: string | null;
}): string | null {
  return art.poster_preview_url ?? art.poster_url ?? null;
}

function itemVersion(item: MediaItemRead, primaryHash?: string | null): string {
  return String(primaryHash || item.last_matched_at || item.last_synced_at || 0);
}

/**
 * An item's art: its local file first, then the media server's copy. Without
 * a size it is the original image.
 */
function itemArtUrl(
  item: MediaItemRead | null,
  artType: "poster" | "background",
  size?: ImageSize,
): string | null {
  if (!item) return null;
  const hash = artType === "poster" ? item.poster_hash : item.background_hash;
  if (hash) {
    return localItemImageUrl(
      { item_id: item.id, art_type: artType },
      { t: itemVersion(item, hash), size },
    );
  }
  if (item.server_item_id) {
    return itemProviderArtUrl({ item_id: item.id }, { type: artType, t: itemVersion(item), size });
  }
  // Remote links are never shown in place of a file, except for an item
  // without a folder (chosen from TMDB), which can only ever show its choice.
  if (item.folder_path) return null;
  if (artType === "background") return item.background_url;
  return size ? remotePosterUrl(item) : item.poster_url;
}

/**
 * The one URL an item's art is shown by, in the sidebar, on the detail page
 * and when fetched ahead, so an image loaded once shows everywhere at once.
 * Local and media server art use their display thumbnail; a remote poster
 * uses its preview.
 */
export function itemArtDisplayUrl(
  item: MediaItemRead | null,
  artType: "poster" | "background",
): string | null {
  return itemArtUrl(item, artType, "display");
}

/** The original poster, for opening in a new tab. */
export function itemPosterOriginalUrl(item: MediaItemRead | null): string | null {
  return itemArtUrl(item, "poster");
}

export function seasonPosterUrls(
  item: MediaItemRead | null,
  season: SeasonRead,
): { src: string | null; fallbackSrc: string | null } {
  if (!item) return { src: null, fallbackSrc: null };

  const localUrl = season.poster_hash
    ? localSeasonImageUrl({ season_id: season.id }, { t: season.poster_hash, size: "display" })
    : null;
  const serverUrl = season.server_item_id
    ? seasonProviderArtUrl(
        { season_id: season.id },
        { t: String(season.poster_hash || item.last_synced_at || 0), size: "display" },
      )
    : null;

  if (localUrl) return { src: localUrl, fallbackSrc: serverUrl };
  // As for items, only a season of an item without a folder shows its remote choice.
  const chosenUrl = item.folder_path ? null : remotePosterUrl(season);
  return { src: serverUrl ?? chosenUrl, fallbackSrc: null };
}

/** How an art candidate is shown in the art grid. */
export function candidateImageUrl(art: ArtCandidate): string {
  return art.preview_url || art.url;
}

/** The detail page's poster and, when it is shown, background for an item. */
export function itemDetailImageUrls(item: MediaItemRead, withBackground: boolean): string[] {
  return [
    itemArtDisplayUrl(item, "poster"),
    withBackground ? itemArtDisplayUrl(item, "background") : null,
  ].filter((url): url is string => url !== null);
}

/**
 * A collection's art, like an item's: the image Overture uploaded, from its
 * cache, then the media server's copy, named by its version. Without a size
 * it is the original image.
 */
function collectionArtUrl(
  collection: CollectionRead | null,
  artType: "poster" | "background",
  size?: ImageSize,
): string | null {
  if (!collection) return null;
  const hash = artType === "poster" ? collection.poster_hash : collection.background_hash;
  if (hash) {
    return localCollectionImageUrl(
      { collection_id: collection.id, art_type: artType },
      { t: hash, size },
    );
  }
  const version =
    artType === "poster" ? collection.server_poster_version : collection.server_background_version;
  return version
    ? collectionProviderArtUrl(
        { collection_id: collection.id, art_type: artType },
        { t: version, size },
      )
    : null;
}

/** The one URL a collection's art is shown by, in the sidebar and on the detail page. */
export function collectionArtDisplayUrl(
  collection: CollectionRead | null,
  artType: "poster" | "background",
): string | null {
  return collectionArtUrl(collection, artType, "display");
}

/** The original poster, for opening in a new tab. */
export function collectionPosterOriginalUrl(collection: CollectionRead | null): string | null {
  return collectionArtUrl(collection, "poster");
}
