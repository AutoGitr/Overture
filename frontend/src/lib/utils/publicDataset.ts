import type {
  CatalogEntry,
  MediaItemRead,
  PublicDatasetRecord,
  SeasonRead,
} from "../../generated/rest/types.gen";

function value(v: string | number | boolean | null | undefined): string {
  if (v === null || v === undefined) return "";
  return String(v);
}

export function hasContributionValues(
  item: MediaItemRead | null,
  seasons: SeasonRead[] = [],
): boolean {
  if (!item) return false;
  if (item.poster_url || item.background_url || item.youtube_id) {
    return true;
  }
  return seasons.some((season) => !!season.poster_url);
}

export function buildContributionIssueUrl(
  repoUrl: string,
  item: CatalogEntry | MediaItemRead,
  seasons: Pick<SeasonRead, "season_num" | "poster_url">[] = [],
): string {
  const isShow = item.media_type === "show";

  const seasonPosters = (seasons.length ? seasons : "seasons" in item ? (item.seasons ?? []) : [])
    .map((season) => [season.season_num, season.poster_url] as const)
    .filter(([, posterUrl]) => !!posterUrl)
    .map(([seasonNum, posterUrl]) => `${seasonNum}=${posterUrl}`)
    .join("\n");

  const params = new URLSearchParams();
  params.set("template", `${item.media_type}.yml`);
  const year = value(item.year);
  params.set(
    "title",
    `${item.media_type === "collection" ? "[Collection]" : isShow ? "[Show]" : "[Movie]"}: ${value(item.title)}${year ? ` (${year})` : ""}`,
  );
  params.set("item_title", value(item.title));
  params.set("year", value(item.year));
  params.set("tmdb_id", value(item.tmdb_id));
  params.set("tvdb_id", value(item.tvdb_id));
  params.set("imdb_id", value(item.imdb_id));
  params.set("poster_url", value(item.poster_url));
  params.set("background_url", value(item.background_url));
  params.set(
    "youtube_id",
    value("youtube_id" in item ? item.youtube_id : item.youtube_id_overturedb),
  );
  if (isShow) {
    params.set("season_posters", seasonPosters);
  }
  return `${repoUrl.replace(/\/$/, "")}/issues/new?${params.toString()}`;
}

function normalise(v: string | number | boolean | null | undefined): string {
  return value(v).trim();
}

function populatedValueMatches(
  current: string | number | boolean | null | undefined,
  publicValue: string | number | boolean | null | undefined,
): boolean {
  const currentValue = normalise(current);
  if (!currentValue) return true;
  return currentValue === normalise(publicValue);
}

export function selectionMatchesPublicDataset(
  item: MediaItemRead | null,
  seasons: SeasonRead[] = [],
  record: PublicDatasetRecord | null = null,
): boolean {
  if (!item || !record?.item || !hasContributionValues(item, seasons)) {
    return false;
  }

  if (!populatedValueMatches(item.poster_url, record.item.poster_url)) {
    return false;
  }
  if (!populatedValueMatches(item.background_url, record.item.background_url)) {
    return false;
  }
  const youtubeId = normalise(item.youtube_id);
  if (
    youtubeId &&
    youtubeId !== normalise(record.item.youtube_id_overturedb) &&
    youtubeId !== normalise(record.item.youtube_id_themerrdb)
  ) {
    return false;
  }

  const publicSeasonPosters = new Map(
    (record.seasons ?? []).map((season) => [season.season_num, normalise(season.poster_url)]),
  );

  for (const season of seasons) {
    const posterUrl = normalise(season.poster_url);
    if (!posterUrl) continue;
    if (publicSeasonPosters.get(season.season_num) !== posterUrl) {
      return false;
    }
  }

  return true;
}
