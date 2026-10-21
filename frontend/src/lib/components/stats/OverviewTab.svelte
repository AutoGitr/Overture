<script lang="ts">
  import Clapperboard from "@lucide/svelte/icons/clapperboard";
  import Database from "@lucide/svelte/icons/database";
  import HardDrive from "@lucide/svelte/icons/hard-drive";
  import Image from "@lucide/svelte/icons/image";
  import Layers from "@lucide/svelte/icons/layers";
  import MonitorPlay from "@lucide/svelte/icons/monitor-play";
  import Music from "@lucide/svelte/icons/music";
  import Tv from "@lucide/svelte/icons/tv";
  import type { Component, Snippet } from "svelte";
  import type { StatsResponse } from "../../../generated/rest/types.gen";
  import { formatBytes } from "../../utils/popupFormat";

  let { stats }: { stats: StatsResponse } = $props();

  /** Each part of the footprint, in the order the bar stacks them. */
  let storageSegments = $derived.by(() => {
    const total = stats.storage.total_footprint_bytes || 1;
    return [
      { label: "Artwork", bytes: stats.storage.artwork_size_bytes, tone: "seg-art" },
      { label: "Themes", bytes: stats.storage.themes_size_bytes, tone: "seg-theme" },
      { label: "Database", bytes: stats.storage.database_size_bytes, tone: "seg-db" },
      { label: "Backups", bytes: stats.storage.backups_size_bytes, tone: "seg-backup" },
    ].map((segment) => ({ ...segment, percent: ((segment.bytes / total) * 100).toFixed(1) }));
  });

  let collectionsKnown = $derived(
    stats.library.total_collections != null && stats.library.monitored_collections != null,
  );
</script>

{#snippet kpi(
  Icon: Component<{ size?: number }>,
  title: string,
  value: string,
  sub: Snippet,
  highlight = false,
)}
  <div class={["kpi-card", { highlight }]}>
    <div class="kpi-header">
      <span class={["kpi-icon", { accent: highlight }]}><Icon size={16} /></span>
      <span>{title}</span>
    </div>
    <div class="kpi-value">{value}</div>
    <div class="kpi-sub">{@render sub()}</div>
  </div>
{/snippet}

{#snippet footprintSub()}
  Artwork, themes, database, and backups
{/snippet}

{#snippet artworkSub()}
  {stats.art.overall.local_files.toLocaleString()} local files ({stats.art.overall
    .local_percentage}% local &middot; {stats.art.overall.matched_percentage}% matched)
{/snippet}

{#snippet themeSub()}
  {stats.themes.overall.local_files.toLocaleString()} local audio files ({stats.themes.overall
    .local_percentage}% local &middot; {stats.themes.overall.matched_percentage}% matched)
{/snippet}

{#snippet databaseSub()}
  DB: {formatBytes(stats.storage.database_size_bytes)} &middot; Backups: {formatBytes(
    stats.storage.backups_size_bytes,
  )}
{/snippet}

{#snippet libraryStat(
  Icon: Component<{ size?: number }>,
  name: string,
  count: number | null,
  details: Snippet,
)}
  <div class="library-stat-card">
    <div class="lib-stat-header">
      <Icon size={16} />
      <span>{name}</span>
    </div>
    <div class="lib-stat-count">
      {#if count === null}&ndash;{:else}{count.toLocaleString()}{/if}
    </div>
    <div class="lib-stat-details">{@render details()}</div>
  </div>
{/snippet}

{#snippet monitoring(monitored: number, unmonitored: number)}
  <span class="text-success">{monitored.toLocaleString()} monitored</span>
  {#if unmonitored > 0}
    <span class="text-muted">&middot; {unmonitored.toLocaleString()} unmonitored</span>
  {/if}
{/snippet}

{#snippet movieDetails()}
  {@render monitoring(stats.library.monitored_movies, stats.library.unmonitored_movies)}
{/snippet}

{#snippet showDetails()}
  {@render monitoring(stats.library.monitored_shows, stats.library.unmonitored_shows)}
{/snippet}

{#snippet seasonDetails()}
  <span class="text-info">{stats.library.seasons_with_episodes.toLocaleString()} with episodes</span
  >
{/snippet}

{#snippet collectionDetails()}
  {#if collectionsKnown}
    <span class="text-accent"
      >{(stats.library.monitored_collections ?? 0).toLocaleString()} monitored</span
    >
  {:else}
    <span class="text-muted">Unavailable from media server</span>
  {/if}
{/snippet}

<div class="kpi-grid">
  {@render kpi(
    HardDrive,
    "Total Footprint",
    formatBytes(stats.storage.total_footprint_bytes),
    footprintSub,
    true,
  )}
  {@render kpi(Image, "Artwork", formatBytes(stats.storage.artwork_size_bytes), artworkSub)}
  {@render kpi(Music, "Theme Music", formatBytes(stats.storage.themes_size_bytes), themeSub)}
  {@render kpi(
    Database,
    "Database & Backups",
    formatBytes(stats.storage.database_size_bytes + stats.storage.backups_size_bytes),
    databaseSub,
  )}
</div>

<section class="option-card">
  <span class="form-label">Storage Distribution</span>
  <div class="multi-progress-bar" aria-label="Storage allocation bar">
    {#each storageSegments as segment (segment.label)}
      <div
        class="bar-seg {segment.tone}"
        style:width="{segment.percent}%"
        title="{segment.label}: {formatBytes(segment.bytes)} ({segment.percent}%)"
      ></div>
    {/each}
  </div>
  <div class="legend-row">
    {#each storageSegments as segment (segment.label)}
      <div class="legend-item">
        <span class="legend-dot {segment.tone}"></span>
        <span>{segment.label} ({segment.percent}%)</span>
      </div>
    {/each}
  </div>
</section>

<section class="option-card">
  <span class="form-label">Library Breakdown</span>
  <div class="library-grid">
    {@render libraryStat(Clapperboard, "Movies", stats.library.total_movies, movieDetails)}
    {@render libraryStat(Tv, "TV Shows", stats.library.total_shows, showDetails)}
    {@render libraryStat(Layers, "Seasons", stats.library.total_seasons, seasonDetails)}
    {@render libraryStat(
      MonitorPlay,
      "Collections",
      collectionsKnown ? (stats.library.total_collections ?? null) : null,
      collectionDetails,
    )}
  </div>
</section>

<style>
  .kpi-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: var(--space-3);
  }

  .kpi-card {
    background: var(--bg-secondary);
    border: var(--border-subtle);
    border-radius: var(--radius-md);
    padding: var(--space-3) var(--space-4);
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }

  .kpi-card.highlight {
    border-color: oklch(from var(--accent) l c h / 0.3);
    background: color-mix(in oklch, var(--accent) 5%, var(--bg-secondary));
  }

  .kpi-header {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    color: var(--text-secondary);
    font-size: var(--text-xs);
    font-weight: 500;
  }

  .kpi-icon {
    display: inline-flex;
  }

  .accent {
    color: var(--accent);
  }

  .kpi-value {
    font-family: var(--font-mono);
    font-size: var(--text-xl);
    font-weight: 700;
    color: var(--text-primary);
    letter-spacing: -0.02em;
  }

  .kpi-sub {
    font-size: var(--text-xs);
    color: var(--text-tertiary);
    white-space: normal;
    line-height: 1.35;
    word-break: break-word;
  }

  .multi-progress-bar {
    display: flex;
    height: 12px;
    border-radius: var(--radius-full);
    overflow: hidden;
    background: var(--bg-elevated);
    margin: var(--space-2) 0 var(--space-3);
  }

  .bar-seg {
    height: 100%;
  }

  .seg-art {
    background: var(--info);
  }

  .seg-theme {
    background: var(--success);
  }

  .seg-db {
    background: var(--warning);
  }

  .seg-backup {
    background: var(--violet);
  }

  .legend-row {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-4);
    font-size: var(--text-xs);
    color: var(--text-secondary);
  }

  .legend-item {
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }

  .legend-dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
  }

  .library-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: var(--space-3);
    margin-top: var(--space-2);
  }

  .library-stat-card {
    background: var(--bg-elevated);
    border: var(--border-subtle);
    border-radius: var(--radius-sm);
    padding: var(--space-3);
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }

  .lib-stat-header {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    color: var(--text-secondary);
    font-size: var(--text-xs);
  }

  .lib-stat-count {
    font-family: var(--font-mono);
    font-size: var(--text-lg);
    font-weight: 700;
    color: var(--text-primary);
  }

  .lib-stat-details {
    font-size: var(--text-xs);
  }
</style>
