<script lang="ts">
  import ChartColumn from "@lucide/svelte/icons/chart-column";
  import Database from "@lucide/svelte/icons/database";
  import Film from "@lucide/svelte/icons/film";
  import Image from "@lucide/svelte/icons/image";
  import Images from "@lucide/svelte/icons/images";
  import LayoutDashboard from "@lucide/svelte/icons/layout-dashboard";
  import Music from "@lucide/svelte/icons/music";
  import RefreshCw from "@lucide/svelte/icons/refresh-cw";
  import { createQuery } from "@tanstack/svelte-query";
  import { getStatsOptions } from "../../generated/rest/@tanstack/svelte-query.gen";
  import CoverageCard from "../components/CoverageCard.svelte";
  import DataStatus from "../components/DataStatus.svelte";
  import PopupShell from "../components/PopupShell.svelte";
  import PopupTabs from "../components/PopupTabs.svelte";
  import DatabaseTab from "../components/stats/DatabaseTab.svelte";
  import OverviewTab from "../components/stats/OverviewTab.svelte";
  import { uiState } from "../stores/uiState.svelte";
  import { MEDIA_ICONS } from "../utils/mediaIcons";
  import { formatDateInTimezone } from "../utils/popupFormat";

  const TABS = [
    { id: "overview", label: "Overview", icon: LayoutDashboard },
    { id: "art", label: "Artwork", icon: Image },
    { id: "themes", label: "Themes", icon: Music },
    { id: "database", label: "Database", icon: Database },
  ] as const;
  let activeTab = $state<(typeof TABS)[number]["id"]>("overview");

  const statsQuery = createQuery(() => getStatsOptions());
  let data = $derived(statsQuery.data);
</script>

<PopupShell title="Statistics" size="wide" onclose={() => uiState.closePopup()}>
  {#snippet icon()}
    <ChartColumn size={18} />
  {/snippet}

  {#snippet tabs()}
    <PopupTabs
      tabs={TABS}
      active={activeTab}
      label="Statistics views"
      idPrefix="stats"
      onselect={(tab) => (activeTab = tab)}
    />
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
    <div
      class="tab-content"
      role="tabpanel"
      id="stats-panel-{activeTab}"
      aria-labelledby="stats-tab-{activeTab}"
    >
      {#if activeTab === "overview"}
        <OverviewTab stats={data} />
      {:else if activeTab === "art"}
        <CoverageCard title="Overall artwork coverage" icon={Images} coverage={data.art.overall} />
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
          title="Season posters"
          icon={MEDIA_ICONS.season}
          coverage={data.art.season_poster}
          showAverage
        />
        {#if data.art.collections}
          <CoverageCard
            title="Collection artwork"
            icon={MEDIA_ICONS.collection}
            coverage={data.art.collections}
            showAverage
          />
        {/if}
      {:else if activeTab === "themes"}
        <CoverageCard
          title="Overall theme coverage"
          icon={Music}
          coverage={data.themes.overall}
        />
        <CoverageCard title="Movie themes" icon={MEDIA_ICONS.movie} coverage={data.themes.movies} />
        <CoverageCard title="TV Show themes" icon={MEDIA_ICONS.show} coverage={data.themes.shows} />
        {#if data.themes.collections}
          <CoverageCard
            title="Collection themes"
            icon={MEDIA_ICONS.collection}
            coverage={data.themes.collections}
          />
        {:else}
          <section class="option-card">
            <h3 class="form-label">Collection themes</h3>
            <p class="text-muted">Unavailable: the media server could not list its collections.</p>
          </section>
        {/if}
      {:else if activeTab === "database"}
        <DatabaseTab stats={data} />
      {/if}
    </div>
  {/if}

  {#snippet footer()}
    {#if data}
      <span class="stats-timestamp actions-start">
        Updated {formatDateInTimezone(data.generated_at, "UTC")}
      </span>
    {/if}
    <button type="button" class="btn btn-secondary" onclick={() => uiState.closePopup()}>
      Close
    </button>
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

  .tab-content {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
  }

  .stats-timestamp {
    font-size: var(--text-xs);
    color: var(--text-tertiary);
  }
</style>
