<script lang="ts">
  import Layers from "@lucide/svelte/icons/layers";
  import type {
    MediaItemRead,
    SeasonRead,
    TmdbItemPreview,
    TmdbSeasonPreview,
  } from "../../generated/rest/types.gen";
  import { createSeasonsQuery } from "../rest/queries";
  import { goToCatalogEntry, goToSeason } from "../router/routes";
  import type { CatalogContext } from "../utils/catalogDraft";
  import { remotePosterUrl, seasonPosterUrls } from "../utils/artDisplay";
  import PosterCard from "./PosterCard.svelte";
  import DataStatus from "./DataStatus.svelte";
  import ImageGrid from "./ImageGrid.svelte";

  let {
    item,
    preview,
    catalog = null,
  }: {
    item: MediaItemRead | null;
    preview: TmdbItemPreview | null;
    catalog?: CatalogContext | null;
  } = $props();

  let subject = $derived(item ?? preview);
  const seasonsQuery = createSeasonsQuery(() => item);
  // A TMDB title's seasons come with it; a stored show's are loaded.
  let seasons = $derived<(SeasonRead | TmdbSeasonPreview)[]>(
    catalog ? catalog.seasons : item ? (seasonsQuery.data ?? []) : (preview?.seasons ?? []),
  );
  let seasonsLoaded = $derived(!item || seasonsQuery.isSuccess);

  function posterUrls(season: SeasonRead | TmdbSeasonPreview) {
    return "id" in season
      ? seasonPosterUrls(item, season)
      : { src: remotePosterUrl(season), fallbackSrc: null };
  }

  function drillInto(season: SeasonRead | TmdbSeasonPreview) {
    if (catalog)
      goToCatalogEntry(catalog.target, {
        mode: "art",
        artSubTab: "seasons",
        drillSeasonNum: season.season_num,
      });
    else if (subject) goToSeason(subject, season);
  }
</script>

<div class="season-grid">
  {#if item}
    <DataStatus
      label="seasons"
      error={seasonsQuery.error}
      loading={seasonsQuery.isFetching}
      hasData={seasonsQuery.data !== undefined}
      onretry={() => seasonsQuery.refetch()}
    />
  {/if}
  {#if seasonsLoaded && seasons.length === 0}
    <div class="empty-state">
      <Layers size={32} />
      <p>No seasons found</p>
    </div>
  {:else if seasons.length > 0}
    <ImageGrid>
      {#each seasons as season (season.season_num)}
        {@const { src, fallbackSrc } = posterUrls(season)}

        <PosterCard
          title={season.title || `Season ${season.season_num}`}
          {src}
          {fallbackSrc}
          onselect={() => drillInto(season)}
          meta={"file_count" in season && season.file_count
            ? `${season.file_count} file${season.file_count === 1 ? "" : "s"}`
            : null}
        />
      {/each}
    </ImageGrid>
  {/if}
</div>

<style>
  .season-grid {
    display: flex;
    flex-direction: column;
  }

  .empty-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: var(--space-3);
    padding: var(--space-10);
    color: var(--text-tertiary);
  }
</style>
