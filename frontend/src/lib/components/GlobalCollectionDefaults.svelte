<script lang="ts">
  import { createQuery } from "@tanstack/svelte-query";
  import {
    getCollectionArrOptionsOptions,
    getCollectionCapabilitiesOptions,
    listCollectionsOptions,
  } from "../../generated/rest/@tanstack/svelte-query.gen";
  import type { AppSettingsUpdate, MediaType } from "../../generated/rest/types.gen";
  import { goToCollectionsList } from "../router/routes";
  import { settingsState } from "../stores/settingsState.svelte";
  import { uiState } from "../stores/uiState.svelte";
  import CollectionPolicyFields, { type PolicyData } from "./CollectionPolicyFields.svelte";
  import CollectionScheduleFields, { type ScheduleData } from "./CollectionScheduleFields.svelte";
  import DataStatus from "./DataStatus.svelte";

  let { draft }: { draft: AppSettingsUpdate } = $props();
  const id = $props.id();

  /** Each setting's global name; groups and collections use the policy's. */
  const GLOBAL_NAMES = {
    sync_mode: "collection_sync_mode",
    minimum_items: "collection_minimum_items",
    delete_below_minimum: "collection_delete_below_minimum",
    auto_match_art: "collection_auto_match_art",
    auto_match_theme: "collection_auto_match_theme",
    request_missing: "collection_request_missing",
    collection_mode: "collection_mode_default",
    order_type: "collection_order_default",
    collection_filtering: "collection_filtering_default",
    visible_home: "collection_visible_home",
    visible_shared: "collection_visible_shared",
    visible_library: "collection_visible_library",
    sort_title_format: "collection_sort_title_format",
    summary_format: "collection_summary_format",
    sync_schedule: "collection_sync_schedule",
    sync_enabled: "collection_sync_enabled",
    delete_when_inactive: "collection_delete_when_inactive",
  } as const satisfies Partial<Record<keyof (PolicyData & ScheduleData), keyof AppSettingsUpdate>>;
  const TEXT = new Set(["sort_title_format", "summary_format", "sync_schedule"]);

  // Global defaults always hold a value: cleared text is empty, other blanks are ignored.
  const policy: PolicyData & ScheduleData = {};
  for (const [name, global] of Object.entries(GLOBAL_NAMES)) {
    Object.defineProperty(policy, name, {
      enumerable: true,
      get: () => draft[global],
      set: (value: unknown) => {
        if (value != null || TEXT.has(name)) Object.assign(draft, { [global]: value ?? "" });
      },
    });
  }

  const capabilities = createQuery(() =>
    getCollectionCapabilitiesOptions({ query: { media_type: "movie" } }),
  );
  const ARR = [
    ["movie", "Radarr", "radarr"],
    ["show", "Sonarr", "sonarr"],
  ] as const satisfies readonly (readonly [MediaType, string, string])[];
  const radarr = createQuery(() => ({
    ...getCollectionArrOptionsOptions({ query: { media_type: "movie" } }),
    enabled: settingsState.current.radarr_configured,
  }));
  const sonarr = createQuery(() => ({
    ...getCollectionArrOptionsOptions({ query: { media_type: "show" } }),
    enabled: settingsState.current.sonarr_configured,
  }));
  let plex = $derived(settingsState.current.media_server === "plex");

  // Collections that turning the requirement on would leave without a valid group.
  const ungroupedQueries = (["movie", "show"] as const).map((mediaType) => ({
    mediaType,
    query: createQuery(() => ({
      ...listCollectionsOptions({ query: { media_type: mediaType } }),
      enabled: !!draft.collection_require_group,
    })),
  }));
  let ungrouped = $derived(
    ungroupedQueries.map(({ mediaType, query }) => ({
      mediaType,
      count: (query.data ?? []).filter((row) => row.managed && !row.collection_group).length,
    })),
  );
  let anyArr = $derived(
    settingsState.current.radarr_configured || settingsState.current.sonarr_configured,
  );
</script>

<label class="form-row">
  <input type="checkbox" bind:checked={draft.collection_import_unmanaged} />Import new unmanaged
  collections during Sync
</label>
<p class="hint">
  Off leaves new server collections outside Overture; existing imports are kept. Groups and
  collections can override everything below.
</p>
<label class="form-row">
  <input type="checkbox" bind:checked={draft.collection_require_group} />Require a group for every
  managed collection
</label>
{#if draft.collection_require_group}
  {#each ungrouped.filter((entry) => entry.count > 0) as entry (entry.mediaType)}
    <p class="hint">
      {entry.count}
      {entry.mediaType === "movie" ? "movie" : "show"}
      {entry.count === 1 ? "collection has" : "collections have"} no group yet and cannot be saved until
      it has one.
      <button
        type="button"
        class="btn btn-ghost btn-sm"
        onclick={() => {
          uiState.closePopup();
          goToCollectionsList(entry.mediaType);
        }}>Show them</button
      >
    </p>
  {/each}
{/if}
{#if settingsState.current.tmdb_configured}
  <div class="form-label">
    <label for={`${id}-region`}>TMDB region</label>
    <input
      id={`${id}-region`}
      maxlength="2"
      required
      bind:value={draft.tmdb_region}
      placeholder="US"
      class="text-input-mono"
    />
    <span class="hint">Two-letter country code for TMDB charts and streaming services.</span>
  </div>
{/if}

<span class="form-label">Settings</span>
<div class="options-col">
  <CollectionPolicyFields
    {policy}
    level="global"
    {plex}
    orders={capabilities.data?.orders ?? []}
    arr={anyArr ? "Radarr or Sonarr" : null}
  />
</div>
<span class="form-label">Schedule</span>
<div class="options-col">
  <CollectionScheduleFields {policy} level="global" />
</div>

{#if anyArr}
  <span class="form-label">Requests</span>
  <p class="hint">Where Request missing adds titles, and whether it searches for them.</p>
  {#each ARR as [mediaType, name, key] (key)}
    {@const options = mediaType === "movie" ? radarr : sonarr}
    {#if settingsState.current[`${key}_configured`]}
      <DataStatus
        label={`${name} options`}
        error={options.error}
        loading={options.isFetching}
        hasData={options.data !== undefined}
        onretry={() => options.refetch()}
      />
      <div class="options-col">
        <label class="form-label">
          {name} root folder
          <select bind:value={draft[`${key}_root_folder`]}>
            <option value="">Choose a folder</option>
            {#each options.data?.root_folders ?? [] as folder (folder)}
              <option value={folder}>{folder}</option>
            {/each}
          </select>
        </label>
        <label class="form-label">
          {name} quality profile
          <select bind:value={draft[`${key}_quality_profile_id`]}>
            <option value={null}>Choose a profile</option>
            {#each options.data?.quality_profiles ?? [] as profile (profile.id)}
              <option value={profile.id}>{profile.label}</option>
            {/each}
          </select>
        </label>
        <label class="form-row">
          <input type="checkbox" bind:checked={draft[`${key}_search`]} />Search when added
        </label>
      </div>
    {/if}
  {/each}
{/if}
