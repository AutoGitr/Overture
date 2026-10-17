<script lang="ts">
  import ChevronRight from "@lucide/svelte/icons/chevron-right";
  import type { SeasonRead, TmdbSeasonPreview } from "../../generated/rest/types.gen";
  import { createSeasonsQuery } from "../rest/queries";
  import { goToSeason, goToSeasonsList } from "../router/routes";
  import { selectedState } from "../stores/selectedState.svelte";
  import type { ArtSlotTarget } from "../utils/tmdbItems";
  import ArtSlotPanel from "./ArtSlotPanel.svelte";
  import DataStatus from "./DataStatus.svelte";

  let item = $derived(selectedState.item);
  let preview = $derived(selectedState.preview);
  let subject = $derived(selectedState.subject);
  let artType = $derived(selectedState.currentArtType);
  const seasonsQuery = createSeasonsQuery(() => item);
  // A TMDB title's seasons come with it; a stored show's are loaded.
  let seasons = $derived<(SeasonRead | TmdbSeasonPreview)[]>(
    item ? (seasonsQuery.data ?? []) : (preview?.seasons ?? []),
  );
  let seasonsLoaded = $derived(!item || seasonsQuery.isSuccess);
  let drillSeason = $derived(
    seasons.find((season) => season.season_num === selectedState.drillSeasonNum) ?? null,
  );
  let seasonId = $derived(
    seasonsQuery.data?.find((season) => season.season_num === drillSeason?.season_num)?.id ?? null,
  );

  let slot = $derived.by((): ArtSlotTarget | null => {
    if (artType === "season_poster" && !drillSeason) return null;
    if (item) return { kind: "item", itemId: item.id, seasonId };
    if (!preview) return null;
    return {
      kind: "tmdb",
      mediaType: preview.media_type,
      tmdbId: preview.tmdb_id,
      seasonNum: drillSeason?.season_num ?? null,
    };
  });
  let slotKey = $derived(
    slot?.kind === "item"
      ? `${slot.itemId}-${artType}-${slot.seasonId ?? ""}`
      : `tmdb-${slot?.mediaType}-${slot?.tmdbId}-${artType}-${slot?.seasonNum ?? ""}`,
  );

  $effect(() => {
    if (!subject || artType !== "season_poster") return;
    if (seasonsLoaded && !drillSeason) goToSeasonsList(subject);
  });

  let breadcrumbs = $derived(
    subject
      ? [
          subject.title,
          ...(drillSeason ? [drillSeason.title || `Season ${drillSeason.season_num}`] : []),
        ]
      : [],
  );

  let seasonIndex = $derived(
    drillSeason && artType === "season_poster" ? seasons.indexOf(drillSeason) : -1,
  );

  let canGoPrev = $derived(seasonIndex > 0);
  let canGoNext = $derived(seasonIndex !== -1 && seasonIndex < seasons.length - 1);

  function goToOffset(offset: number) {
    const next = seasons[seasonIndex + offset];
    if (subject && next) goToSeason(subject, next);
  }
</script>

<div class="art-panel">
  {#if artType === "season_poster" && item}
    <DataStatus
      label="season"
      error={seasonsQuery.error}
      loading={seasonsQuery.isFetching}
      hasData={seasonsQuery.data !== undefined}
      onretry={() => seasonsQuery.refetch()}
    />
  {/if}
  {#if breadcrumbs.length > 1}
    <div class="header-row">
      <nav class="breadcrumbs">
        {#each breadcrumbs as label, idx (idx)}
          {#if idx > 0}
            <ChevronRight size={12} />
          {/if}
          {#if idx < breadcrumbs.length - 1}
            <button
              class="breadcrumb-link"
              onclick={() => {
                if (subject) goToSeasonsList(subject);
              }}>{label}</button
            >
          {:else}
            <span class="breadcrumb-current">{label}</span>
          {/if}
        {/each}
      </nav>
      {#if artType === "season_poster"}
        <div class="nav-buttons">
          <button
            class="btn btn-secondary btn-sm"
            disabled={!canGoPrev}
            onclick={() => goToOffset(-1)}>Prev</button
          >
          <button
            class="btn btn-secondary btn-sm"
            disabled={!canGoNext}
            onclick={() => goToOffset(1)}>Next</button
          >
        </div>
      {/if}
    </div>
  {/if}

  {#if slot}
    <!-- Each slot owns its in-flight requests and transient UI state. -->
    {#key slotKey}
      <ArtSlotPanel {slot} {artType} />
    {/key}
  {/if}
</div>

<style>
  .art-panel {
    display: flex;
    flex-direction: column;
    gap: var(--space-5);
  }

  .breadcrumbs {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-size: var(--text-sm);
    color: var(--text-tertiary);
  }

  .breadcrumb-link {
    color: var(--accent);
    font-size: var(--text-sm);
  }
  .breadcrumb-link:hover {
    text-decoration: underline;
  }

  .breadcrumb-current {
    color: var(--text-primary);
  }

  .header-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  .nav-buttons {
    display: flex;
    gap: var(--space-2);
  }

  .nav-buttons .btn {
    padding: var(--space-1) var(--space-3);
  }
</style>
