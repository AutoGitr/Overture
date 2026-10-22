<script lang="ts">
  import ChartColumn from "@lucide/svelte/icons/chart-column";
  import Clapperboard from "@lucide/svelte/icons/clapperboard";
  import Database from "@lucide/svelte/icons/database";
  import Film from "@lucide/svelte/icons/film";
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
  import PopupTabs from "../components/PopupTabs.svelte";
  import DatabaseTab from "../components/stats/DatabaseTab.svelte";
  import OverviewTab from "../components/stats/OverviewTab.svelte";
  import { uiState } from "../stores/uiState.svelte";
  import { formatDateInTimezone } from "../utils/popupFormat";

  const TABS = [
    { id: "overview", label: "Overview", icon: Layers },
    { id: "art", label: "Artwork", icon: Image },
    { id: "themes", label: "Themes", icon: Music },
    { id: "database", label: "Database", icon: Database },
  ] as const;
  let activeTab = $state<(typeof TABS)[number]["id"]>("overview");

  const statsQuery = createQuery(() => getStatsOptions());
  let data = $derived(statsQuery.data);
</script>

<PopupShell
  title="Statistics"
  size="wide"
  --popup-glow-at={(TABS.findIndex((tab) => tab.id === activeTab) + 0.5) / TABS.length}
  onclose={() => uiState.closePopup()}
>
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
      {:else if activeTab === "themes"}
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
      {:else if activeTab === "database"}
        <DatabaseTab stats={data} />
      {/if}
    </div>
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

  .tab-content {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
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
