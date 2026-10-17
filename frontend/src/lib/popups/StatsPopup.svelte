<script lang="ts">
  import ChartColumn from "@lucide/svelte/icons/chart-column";
  import Clapperboard from "@lucide/svelte/icons/clapperboard";
  import Database from "@lucide/svelte/icons/database";
  import Film from "@lucide/svelte/icons/film";
  import HardDrive from "@lucide/svelte/icons/hard-drive";
  import Image from "@lucide/svelte/icons/image";
  import Layers from "@lucide/svelte/icons/layers";
  import MonitorPlay from "@lucide/svelte/icons/monitor-play";
  import Music from "@lucide/svelte/icons/music";
  import RefreshCw from "@lucide/svelte/icons/refresh-cw";
  import Tv from "@lucide/svelte/icons/tv";
  import { createQuery } from "@tanstack/svelte-query";
  import { getStatsOptions } from "../../generated/rest/@tanstack/svelte-query.gen";
  import CoverageCard from "../components/CoverageCard.svelte";
  import DataStatus from "../components/DataStatus.svelte";
  import PopupShell from "../components/PopupShell.svelte";
  import { uiState } from "../stores/uiState.svelte";
  import { formatBytes, formatDateInTimezone } from "../utils/popupFormat";

  const TABS = [
    { id: "overview", label: "Overview", icon: Layers },
    { id: "art", label: "Artwork", icon: Image },
    { id: "themes", label: "Themes", icon: Music },
    { id: "database", label: "Database", icon: Database },
  ] as const;
  let activeTab = $state<(typeof TABS)[number]["id"]>("overview");

  const statsQuery = createQuery(() => getStatsOptions());
  let data = $derived(statsQuery.data);

  /** Each part of the footprint, in the order the bar stacks them. */
  let storageSegments = $derived.by(() => {
    if (!data) return [];
    const total = data.storage.total_footprint_bytes || 1;
    return [
      { label: "Artwork", bytes: data.storage.artwork_size_bytes, tone: "seg-art" },
      { label: "Themes", bytes: data.storage.themes_size_bytes, tone: "seg-theme" },
      { label: "Database", bytes: data.storage.database_size_bytes, tone: "seg-db" },
      { label: "Backups", bytes: data.storage.backups_size_bytes, tone: "seg-backup" },
    ].map((segment) => ({ ...segment, percent: ((segment.bytes / total) * 100).toFixed(1) }));
  });
</script>

<PopupShell title="Statistics" width="min(880px, 95vw)" onclose={() => uiState.closePopup()}>
  {#snippet icon()}
    <ChartColumn size={18} />
  {/snippet}

  {#snippet info()}
    <div class="stats-header-info">
      <span>
        System totals, artwork coverage, theme adoption, database engine metrics, and storage
        footprint.
      </span>
      <button
        type="button"
        class="btn btn-ghost btn-sm refresh-btn"
        disabled={statsQuery.isFetching}
        onclick={() => statsQuery.refetch()}
        title="Refresh statistics"
      >
        <RefreshCw size={13} class={statsQuery.isFetching ? "animate-spin" : ""} />
        <span>Refresh</span>
      </button>
    </div>
  {/snippet}

  <DataStatus
    label="statistics"
    error={statsQuery.error}
    loading={statsQuery.isFetching && !data}
    hasData={data !== undefined}
    onretry={() => statsQuery.refetch()}
  />

  {#if data}
    <div class="stats-nav" role="tablist">
      {#each TABS as tab (tab.id)}
        <button
          type="button"
          class="stats-nav-btn"
          class:active={activeTab === tab.id}
          onclick={() => (activeTab = tab.id)}
          role="tab"
          aria-selected={activeTab === tab.id}
        >
          <tab.icon size={15} />
          <span>{tab.label}</span>
        </button>
      {/each}
    </div>

    {#if activeTab === "overview"}
      <div class="tab-content" role="tabpanel">
        <!-- Storage summary KPI grid -->
        <div class="kpi-grid">
          <div class="kpi-card highlight">
            <div class="kpi-header">
              <HardDrive size={16} class="kpi-icon accent" />
              <span class="kpi-title">Total Footprint</span>
            </div>
            <div class="kpi-value">{formatBytes(data.storage.total_footprint_bytes)}</div>
            <div class="kpi-sub">Artwork, themes, database, and backups</div>
          </div>

          <div class="kpi-card">
            <div class="kpi-header">
              <Image size={16} class="kpi-icon" />
              <span class="kpi-title">Artwork</span>
            </div>
            <div class="kpi-value">{formatBytes(data.storage.artwork_size_bytes)}</div>
            <div class="kpi-sub">
              {data.art.overall.local_files.toLocaleString()} local files ({data.art.overall
                .local_percentage}% local &middot; {data.art.overall.matched_percentage}% matched)
            </div>
          </div>

          <div class="kpi-card">
            <div class="kpi-header">
              <Music size={16} class="kpi-icon" />
              <span class="kpi-title">Theme Music</span>
            </div>
            <div class="kpi-value">{formatBytes(data.storage.themes_size_bytes)}</div>
            <div class="kpi-sub">
              {data.themes.overall.local_files.toLocaleString()} local audio files ({data.themes
                .overall.local_percentage}% local &middot; {data.themes.overall.matched_percentage}%
              matched)
            </div>
          </div>

          <div class="kpi-card">
            <div class="kpi-header">
              <Database size={16} class="kpi-icon" />
              <span class="kpi-title">Database & Backups</span>
            </div>
            <div class="kpi-value">
              {formatBytes(data.storage.database_size_bytes + data.storage.backups_size_bytes)}
            </div>
            <div class="kpi-sub">
              DB: {formatBytes(data.storage.database_size_bytes)} &middot; Backups: {formatBytes(
                data.storage.backups_size_bytes,
              )}
            </div>
          </div>
        </div>

        <!-- Storage footprint visualizer -->
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

        <!-- Library counts summary -->
        <section class="option-card">
          <span class="form-label">Library Breakdown</span>
          <div class="library-grid">
            <div class="library-stat-card">
              <div class="lib-stat-header">
                <Clapperboard size={16} />
                <span class="lib-stat-name">Movies</span>
              </div>
              <div class="lib-stat-count">{data.library.total_movies.toLocaleString()}</div>
              <div class="lib-stat-details">
                <span class="text-success"
                  >{data.library.monitored_movies.toLocaleString()} monitored</span
                >
                {#if data.library.unmonitored_movies > 0}
                  <span class="text-secondary"
                    >&middot; {data.library.unmonitored_movies.toLocaleString()} unmonitored</span
                  >
                {/if}
              </div>
            </div>

            <div class="library-stat-card">
              <div class="lib-stat-header">
                <Tv size={16} />
                <span class="lib-stat-name">TV Shows</span>
              </div>
              <div class="lib-stat-count">{data.library.total_shows.toLocaleString()}</div>
              <div class="lib-stat-details">
                <span class="text-success"
                  >{data.library.monitored_shows.toLocaleString()} monitored</span
                >
                {#if data.library.unmonitored_shows > 0}
                  <span class="text-secondary"
                    >&middot; {data.library.unmonitored_shows.toLocaleString()} unmonitored</span
                  >
                {/if}
              </div>
            </div>

            <div class="library-stat-card">
              <div class="lib-stat-header">
                <Layers size={16} />
                <span class="lib-stat-name">Seasons</span>
              </div>
              <div class="lib-stat-count">{data.library.total_seasons.toLocaleString()}</div>
              <div class="lib-stat-details">
                <span class="text-info"
                  >{data.library.seasons_with_episodes.toLocaleString()} with episodes</span
                >
              </div>
            </div>

            <div class="library-stat-card">
              <div class="lib-stat-header">
                <MonitorPlay size={16} />
                <span class="lib-stat-name">Collections</span>
              </div>
              {#if data.library.total_collections != null && data.library.monitored_collections != null}
                <div class="lib-stat-count">{data.library.total_collections.toLocaleString()}</div>
                <div class="lib-stat-details">
                  <span class="text-accent"
                    >{data.library.monitored_collections.toLocaleString()} monitored</span
                  >
                </div>
              {:else}
                <div class="lib-stat-count">&ndash;</div>
                <div class="lib-stat-details">
                  <span class="text-muted">Unavailable from media server</span>
                </div>
              {/if}
            </div>
          </div>
        </section>
      </div>
    {/if}

    {#if activeTab === "art"}
      <div class="tab-content" role="tabpanel">
        <CoverageCard title="Overall Artwork Coverage" icon={Layers} coverage={data.art.overall} />
        <CoverageCard
          title="Posters"
          icon={Image}
          coverage={data.art.poster}
          showAverage
          breakdown={[
            { label: "Movies", coverage: data.art.poster_movies },
            { label: "Shows", coverage: data.art.poster_shows },
          ]}
        />
        <CoverageCard
          title="Backgrounds"
          icon={Film}
          coverage={data.art.background}
          showAverage
          breakdown={[
            { label: "Movies", coverage: data.art.background_movies },
            { label: "Shows", coverage: data.art.background_shows },
          ]}
        />
        <CoverageCard
          title="Season Posters"
          icon={Layers}
          coverage={data.art.season_poster}
          showAverage
        />
      </div>
    {/if}

    {#if activeTab === "themes"}
      <div class="tab-content" role="tabpanel">
        <CoverageCard
          title="Overall Theme Audio Coverage"
          icon={Music}
          coverage={data.themes.overall}
        />
        <CoverageCard title="Movie Themes" icon={Clapperboard} coverage={data.themes.movies} />
        <CoverageCard title="TV Show Themes" icon={Tv} coverage={data.themes.shows} />
        {#if data.themes.collections}
          <CoverageCard
            title="Collection Themes"
            icon={MonitorPlay}
            coverage={data.themes.collections}
          />
        {:else}
          <section class="option-card">
            <h3 class="form-label">Collection Themes</h3>
            <p class="text-muted">Unavailable: the media server could not list its collections.</p>
          </section>
        {/if}
      </div>
    {/if}

    {#if activeTab === "database"}
      <div class="tab-content" role="tabpanel">
        <!-- SQLite Engine Card -->
        <section class="option-card">
          <div class="section-title-row">
            <Database size={16} class="accent" />
            <span class="form-label mb-0">SQLite Engine & Storage</span>
          </div>
          <div class="metrics-row mt-2">
            <div class="metric-item">
              <span class="metric-label">Database File</span>
              <span class="metric-val">{formatBytes(data.database.file_size_bytes)}</span>
            </div>
            {#if data.database.wal_size_bytes > 0}
              <div class="metric-item">
                <span class="metric-label">WAL File</span>
                <span class="metric-val">{formatBytes(data.database.wal_size_bytes)}</span>
              </div>
            {/if}
            <div class="metric-item">
              <span class="metric-label">Total DB Footprint</span>
              <span class="metric-val">{formatBytes(data.database.total_size_bytes)}</span>
            </div>
            <div class="metric-item">
              <span class="metric-label">Pages</span>
              <span class="metric-val"
                >{data.database.page_count.toLocaleString()}
                <span class="dimmed">({data.database.page_size} B/page)</span></span
              >
            </div>
            <div class="metric-item">
              <span class="metric-label">Freelist / Free</span>
              <span class="metric-val"
                >{formatBytes(data.database.free_size_bytes)}
                <span class="dimmed">({data.database.freelist_count} pages)</span></span
              >
            </div>
          </div>
        </section>

        <!-- Database Tables Row Counts -->
        <section class="option-card">
          <span class="form-label">Database Tables ({data.database.tables.length})</span>
          <div class="table-container">
            <table class="stats-table">
              <thead>
                <tr>
                  <th>Table</th>
                  <th>Description</th>
                  <th class="text-right">Rows</th>
                </tr>
              </thead>
              <tbody>
                {#each data.database.tables as t (t.table_name)}
                  <tr>
                    <td><code class="table-name">{t.table_name}</code></td>
                    <td class="text-secondary">{t.description}</td>
                    <td class="text-right font-mono font-bold">{t.row_count.toLocaleString()}</td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
        </section>

        <!-- Backups Summary -->
        <section class="option-card">
          <div class="section-title-row">
            <HardDrive size={16} class="accent" />
            <span class="form-label mb-0">Backups</span>
          </div>
          <div class="metrics-row mt-2">
            <div class="metric-item">
              <span class="metric-label">Total Backups</span>
              <span class="metric-val">{data.backups.total_backups}</span>
            </div>
            <div class="metric-item">
              <span class="metric-label">Backup Storage</span>
              <span class="metric-val">{formatBytes(data.backups.total_size_bytes)}</span>
            </div>
            <div class="metric-item">
              <span class="metric-label">Latest Backup</span>
              <span class="metric-val">
                {data.backups.latest_backup_at
                  ? formatDateInTimezone(data.backups.latest_backup_at, "UTC")
                  : "None"}
              </span>
            </div>
          </div>
        </section>
      </div>
    {/if}
  {/if}

  {#snippet footer()}
    <div class="stats-footer">
      {#if data}
        <span class="stats-timestamp">
          Updated {formatDateInTimezone(data.generated_at, "UTC")}
        </span>
      {:else}
        <span></span>
      {/if}
      <button type="button" class="btn btn-ghost" onclick={() => uiState.closePopup()}>
        Close
      </button>
    </div>
  {/snippet}
</PopupShell>

<style>
  .stats-header-info {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
    width: 100%;
  }

  .refresh-btn {
    display: flex;
    align-items: center;
    gap: var(--space-1);
    flex-shrink: 0;
  }

  .stats-nav {
    display: flex;
    gap: var(--space-1);
    padding: var(--space-1);
    background: var(--bg-secondary);
    border: var(--border-subtle);
    border-radius: var(--radius-md);
    margin-bottom: var(--space-4);
  }

  .stats-nav-btn {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-3);
    border: none;
    border-radius: var(--radius-sm);
    background: transparent;
    color: var(--text-secondary);
    font-size: var(--text-sm);
    font-weight: 500;
    cursor: pointer;
  }

  .stats-nav-btn:hover {
    color: var(--text-primary);
    background: var(--bg-hover);
  }

  .stats-nav-btn.active {
    color: var(--accent-text);
    background: var(--accent);
    font-weight: 600;
  }

  .tab-content {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
  }

  /* KPI Grid */
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

  .kpi-header :global(.accent) {
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

  /* Multi Progress Bar */
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

  /* Library Grid */
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

  /* Metrics Row */
  .metrics-row {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: var(--space-3);
  }

  .metric-item {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .metric-label {
    font-size: var(--text-xs);
    color: var(--text-tertiary);
  }

  .metric-val {
    font-family: var(--font-mono);
    font-size: var(--text-sm);
    font-weight: 600;
    color: var(--text-primary);
  }

  .dimmed {
    color: var(--text-tertiary);
    font-size: var(--text-xs);
    font-weight: normal;
  }

  .section-title-row {
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }

  .section-title-row :global(.accent) {
    color: var(--accent);
  }

  /* Table styling */
  .table-container {
    overflow-x: auto;
    margin-top: var(--space-2);
  }

  .stats-table {
    width: 100%;
    border-collapse: collapse;
    font-size: var(--text-xs);
  }

  .stats-table th {
    text-align: left;
    padding: var(--space-2) var(--space-3);
    color: var(--text-tertiary);
    border-bottom: var(--border-muted);
    font-weight: 500;
  }

  .stats-table td {
    padding: var(--space-2) var(--space-3);
    border-bottom: var(--border-subtle);
    color: var(--text-secondary);
  }

  .table-name {
    font-family: var(--font-mono);
    color: var(--accent);
    font-size: var(--text-xs);
  }

  .font-mono {
    font-family: var(--font-mono);
  }

  .font-bold {
    font-weight: 600;
    color: var(--text-primary);
  }

  .text-right {
    text-align: right;
  }

  .stats-footer {
    display: flex;
    align-items: center;
    justify-content: space-between;
    width: 100%;
    font-size: var(--text-xs);
    color: var(--text-tertiary);
  }
</style>
