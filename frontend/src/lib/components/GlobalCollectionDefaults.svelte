<script lang="ts">
  import { createQuery } from "@tanstack/svelte-query";
  import {
    getCollectionArrOptionsOptions,
    getCollectionCapabilitiesOptions,
  } from "../../generated/rest/@tanstack/svelte-query.gen";
  import type { AppSettingsUpdate, MediaType } from "../../generated/rest/types.gen";
  import { settingsState } from "../stores/settingsState.svelte";
  import CollectionPolicyFields, { type PolicyData } from "./CollectionPolicyFields.svelte";
  import CollectionScheduleFields, { type ScheduleData } from "./CollectionScheduleFields.svelte";
  import DataStatus from "./DataStatus.svelte";
  import FieldRow from "./FieldRow.svelte";

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

  let anyArr = $derived(
    settingsState.current.radarr_configured || settingsState.current.sonarr_configured,
  );
</script>

<h4 class="caps-label">Management</h4>
<label class="form-row justify-between">
  <span>Import new server collections as unmanaged</span>
  <input type="checkbox" bind:checked={draft.collection_import_unmanaged} />
</label>
<p class="hint">
  Off leaves new server collections out of Overture; ones already imported are kept. Either way,
  Overture changes a collection only once it is taken over.
</p>
{#if settingsState.current.tmdb_configured}
  <h4 class="caps-label">Sources</h4>
  <FieldRow
    label="TMDB region"
    for={`${id}-region`}
    hint="Two-letter country code for TMDB charts and streaming services."
  >
    <input
      id={`${id}-region`}
      maxlength="2"
      size="4"
      required
      bind:value={draft.tmdb_region}
      placeholder="US"
      class="text-input-mono"
    />
  </FieldRow>
{/if}

<p class="hint">Groups and collections can override every default below.</p>
<div class="options-col">
  <CollectionPolicyFields
    {policy}
    level="global"
    {plex}
    orders={capabilities.data?.orders ?? []}
    arr={anyArr ? "Radarr or Sonarr" : null}
  />
</div>
<h4 class="caps-label">Schedule</h4>
<div class="options-col">
  <CollectionScheduleFields {policy} level="global" />
</div>

{#if anyArr}
  <h4 class="caps-label">Requests</h4>
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
        <FieldRow label={`${name} root folder`} for={`${id}-${key}-folder`}>
          <select id={`${id}-${key}-folder`} bind:value={draft[`${key}_root_folder`]}>
            <option value="">Choose a folder</option>
            {#each options.data?.root_folders ?? [] as folder (folder)}
              <option value={folder}>{folder}</option>
            {/each}
          </select>
        </FieldRow>
        <FieldRow label={`${name} quality profile`} for={`${id}-${key}-profile`}>
          <select id={`${id}-${key}-profile`} bind:value={draft[`${key}_quality_profile_id`]}>
            <option value={null}>Choose a profile</option>
            {#each options.data?.quality_profiles ?? [] as profile (profile.id)}
              <option value={profile.id}>{profile.label}</option>
            {/each}
          </select>
        </FieldRow>
        <label class="form-row justify-between">
          <span>Search when added</span>
          <input type="checkbox" bind:checked={draft[`${key}_search`]} />
        </label>
      </div>
    {/if}
  {/each}
{/if}

<style>
  h4 {
    margin: var(--space-2) 0 0;
  }
</style>
