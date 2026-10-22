<script lang="ts">
  import Layers from "@lucide/svelte/icons/layers";
  import type {
    MediaItemRead,
    SeasonRead,
    TmdbItemPreview,
    TmdbSeasonPreview,
  } from "../../generated/rest/types.gen";
  import { createSeasonsQuery } from "../rest/queries";
  import { goToSeason } from "../router/routes";
  import { remotePosterUrl, seasonPosterUrls } from "../utils/artDisplay";
  import FallbackImage from "./FallbackImage.svelte";
  import DataStatus from "./DataStatus.svelte";

  let { item, preview }: { item: MediaItemRead | null; preview: TmdbItemPreview | null } = $props();

  let subject = $derived(item ?? preview);
  const seasonsQuery = createSeasonsQuery(() => item);
  // A TMDB title's seasons come with it; a stored show's are loaded.
  let seasons = $derived<(SeasonRead | TmdbSeasonPreview)[]>(
    item ? (seasonsQuery.data ?? []) : (preview?.seasons ?? []),
  );
  let seasonsLoaded = $derived(!item || seasonsQuery.isSuccess);

  function posterUrls(season: SeasonRead | TmdbSeasonPreview) {
    return "id" in season
      ? seasonPosterUrls(item, season)
      : { src: remotePosterUrl(season), fallbackSrc: null };
  }

  function drillInto(season: SeasonRead | TmdbSeasonPreview) {
    if (subject) goToSeason(subject, season);
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
    <div class="grid">
      {#each seasons as season (season.season_num)}
        {@const { src, fallbackSrc } = posterUrls(season)}

        <button class="season-card card card-interactive" onclick={() => drillInto(season)}>
          <div class="season-poster">
            {#snippet placeholder()}
              <div class="poster-placeholder">
                <Layers size={24} />
              </div>
            {/snippet}
            <!-- Named by the title below it. -->
            <FallbackImage {src} {fallbackSrc} alt="" {placeholder} />
          </div>
          <div class="season-info">
            <span class="season-title">{season.title || `Season ${season.season_num}`}</span>
            {#if "file_count" in season && season.file_count}
              <span class="season-files"
                >{season.file_count} file{season.file_count === 1 ? "" : "s"}</span
              >
            {/if}
          </div>
        </button>
      {/each}
    </div>
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

  .grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
    gap: var(--space-4);
  }

  .season-card {
    overflow: hidden;
    padding: 0;
    text-align: left;
  }

  .season-poster {
    aspect-ratio: 2/3;
    overflow: hidden;
    background: var(--bg-tertiary);
  }

  .poster-placeholder {
    width: 100%;
    height: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    color: var(--text-tertiary);
  }

  .season-info {
    padding: var(--space-3);
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .season-title {
    font-size: var(--text-sm);
    font-weight: 500;
  }

  .season-files {
    font-size: var(--text-xs);
    color: var(--text-tertiary);
  }

  @media (max-width: 480px) {
    .grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: var(--space-3);
    }
  }
</style>
