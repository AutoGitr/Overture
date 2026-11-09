<script lang="ts">
  import { alphabetical } from "../utils/alphabetical";
  import { createQuery } from "@tanstack/svelte-query";
  import {
    getCollectionCapabilitiesOptions,
    listRadarrTagsOptions,
    listSonarrTagsOptions,
  } from "../../generated/rest/@tanstack/svelte-query.gen";
  import type {
    CollectionSourceInput,
    MediaType,
    TmdbChart,
    TmdbPersonRole,
  } from "../../generated/rest/types.gen";
  import { splitList } from "../utils/collectionCriteria";
  import { settingsState } from "../stores/settingsState.svelte";
  import IdListInput from "./IdListInput.svelte";
  import { toggleSelectedValue } from "../utils/popupSelection";
  import SourcePicker from "./SourcePicker.svelte";

  let {
    source = $bindable(),
    mediaType,
    label,
  }: {
    source: CollectionSourceInput;
    mediaType: MediaType;
    /** Names the condition the inputs belong to, for assistive technology. */
    label: string;
  } = $props();

  const CHART_LABELS: Record<TmdbChart, string> = {
    popular: "Popular",
    top_rated: "Top rated",
    trending_day: "Trending today",
    trending_week: "Trending this week",
    now_playing: "In cinemas",
    upcoming: "Coming soon",
    airing_today: "Airing today",
    on_the_air: "Airing this week",
  };
  const capabilities = createQuery(() => ({
    ...getCollectionCapabilitiesOptions({ query: { media_type: mediaType } }),
    enabled: source.type === "tmdb_chart",
  }));
  let charts = $derived(
    alphabetical(capabilities.data?.charts ?? [], (chart) => CHART_LABELS[chart]),
  );

  const radarrTags = createQuery(() => ({
    ...listRadarrTagsOptions(),
    enabled: source.type === "radarr_tag",
  }));
  const sonarrTags = createQuery(() => ({
    ...listSonarrTagsOptions(),
    enabled: source.type === "sonarr_tag",
  }));
  let tags = $derived(
    source.type === "radarr_tag"
      ? radarrTags.data
      : source.type === "sonarr_tag"
        ? sonarrTags.data
        : undefined,
  );
  /** Every tag the app knows, and those the condition names even if it lacks them. */
  let tagLabels = $derived.by(() => {
    const known = (tags ?? []).map((tag) => tag.label);
    const named = source.type === "radarr_tag" || source.type === "sonarr_tag" ? source.tags : [];
    return alphabetical([...known, ...named.filter((tag) => !known.includes(tag))], (tag) => tag);
  });

  const ROLES: readonly (readonly [TmdbPersonRole, string])[] = [
    ["actor", "Actor"],
    ["director", "Director"],
    ["producer", "Producer"],
    ["writer", "Writer"],
  ];
</script>

<div class="source-fields">
  {#if source.type === "tmdb_collection"}
    <SourcePicker
      kind="franchise"
      {label}
      id={source.collection_id}
      onpick={(id) => {
        if (source.type === "tmdb_collection") source.collection_id = id;
      }}
    />
  {:else if source.type === "tmdb_list"}
    <IdListInput
      label={`${label} TMDB list IDs`}
      placeholder="TMDB list IDs or links, e.g. 123, 456"
      ids={source.list_ids}
      onchange={(ids) => {
        if (source.type === "tmdb_list") source.list_ids = ids;
      }}
    />
  {:else if source.type === "tmdb_item"}
    <IdListInput
      label={`${label} TMDB IDs`}
      placeholder={`TMDB ${mediaType === "movie" ? "movie" : "show"} IDs or links, e.g. 550, 680`}
      ids={source.tmdb_ids}
      onchange={(ids) => {
        if (source.type === "tmdb_item") source.tmdb_ids = ids;
      }}
    />
    {#if settingsState.current.tmdb_configured}
      <SourcePicker
        kind="title"
        {label}
        {mediaType}
        onpick={(id) => {
          if (source.type === "tmdb_item" && !source.tmdb_ids.includes(id))
            source.tmdb_ids = [...source.tmdb_ids, id];
        }}
      />
    {/if}
  {:else if source.type === "tmdb_person"}
    <SourcePicker
      kind="person"
      {label}
      id={source.person_id}
      onpick={(id, name) => {
        if (source.type !== "tmdb_person") return;
        source.person_id = id;
        // A typed ID names no one, so a name from an earlier pick would mislead.
        source.person_name = name;
      }}
    />
    <input
      aria-label={`${label} person name`}
      placeholder="Name (optional)"
      value={source.person_name ?? ""}
      oninput={(event) => {
        if (source.type === "tmdb_person") source.person_name = event.currentTarget.value || null;
      }}
    />
    <div class="checks" role="group" aria-label={`${label} credits`}>
      {#each ROLES as [role, roleLabel] (role)}
        <label class="check">
          <input
            type="checkbox"
            checked={(source.roles ?? ["actor"]).includes(role)}
            onchange={() => {
              if (source.type === "tmdb_person")
                source.roles = toggleSelectedValue(source.roles ?? ["actor"], role);
            }}
          />
          {roleLabel}
        </label>
      {/each}
    </div>
  {:else if source.type === "tmdb_chart"}
    <select
      aria-label={`${label} TMDB chart`}
      value={source.chart}
      onchange={(event) => {
        const chart = charts.find((entry) => entry === event.currentTarget.value);
        if (source.type === "tmdb_chart" && chart) source.chart = chart;
      }}
    >
      {#each charts as chart (chart)}
        <option value={chart}>{CHART_LABELS[chart]}</option>
      {/each}
    </select>
    <input
      type="number"
      min="1"
      max="500"
      aria-label={`${label} chart length`}
      title="How many of the chart's top titles count"
      value={source.limit ?? 100}
      oninput={(event) => {
        if (source.type === "tmdb_chart" && event.currentTarget.value)
          source.limit = event.currentTarget.valueAsNumber;
      }}
    />
  {:else if source.type === "mdblist"}
    <input
      required
      aria-label={`${label} MDBList lists`}
      placeholder="MDBList list URLs or IDs, or user/list, separated by commas"
      value={source.identifiers.join(", ")}
      onchange={(event) => {
        if (source.type === "mdblist") source.identifiers = splitList(event.currentTarget.value);
      }}
    />
    <SourcePicker
      kind="mdblist"
      {label}
      onpick={(id) => {
        if (source.type === "mdblist" && !source.identifiers.includes(String(id)))
          source.identifiers = [...source.identifiers, String(id)];
      }}
    />
  {:else}
    {@const selected = source.tags}
    {#if tags?.length}
      <div class="checks" role="group" aria-label={`${label} tags`}>
        {#each tagLabels as tag (tag)}
          <button
            type="button"
            class={["btn btn-sm", selected.includes(tag) ? "btn-secondary" : "btn-ghost"]}
            aria-pressed={selected.includes(tag)}
            onclick={() => {
              if (source.type === "radarr_tag" || source.type === "sonarr_tag")
                source.tags = toggleSelectedValue(source.tags, tag);
            }}>{tag}</button
          >
        {/each}
      </div>
    {:else}
      <input
        required
        aria-label={`${label} tags`}
        placeholder="Tag names, separated by commas"
        value={selected.join(", ")}
        onchange={(event) => {
          if (source.type === "radarr_tag" || source.type === "sonarr_tag")
            source.tags = splitList(event.currentTarget.value);
        }}
      />
    {/if}
  {/if}
</div>

<style>
  .source-fields {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    min-width: 0;
  }

  .checks {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2) var(--space-3);
  }

  .check {
    display: flex;
    align-items: center;
    gap: var(--space-1);
    font-size: var(--text-sm);
  }
</style>
