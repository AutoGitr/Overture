<script lang="ts">
  import { createQuery } from "@tanstack/svelte-query";
  import {
    getCollectionArrOptionsOptions,
    getCollectionCapabilitiesOptions,
  } from "../../generated/rest/@tanstack/svelte-query.gen";
  import type { AppSettingsUpdate, MediaType } from "../../generated/rest/types.gen";
  import { settingsState } from "../stores/settingsState.svelte";
  import CollectionPolicyFields from "./CollectionPolicyFields.svelte";
  import CollectionScheduleFields from "./CollectionScheduleFields.svelte";
  import type { PolicyData, ScheduleData } from "../utils/collectionFormShared.svelte";
  import { POLICY_SETTINGS, TEXT_LIMITS } from "../../generated/settings";
  import DataStatus from "./DataStatus.svelte";
  import FieldRow from "./FieldRow.svelte";

  let { draft = $bindable() }: { draft: AppSettingsUpdate } = $props();
  const id = $props.id();

  const TEXT = new Set(["sort_title_format", "summary_format"]);

  // Global defaults always hold a value: cleared text is empty, other blanks are ignored.
  const policy: PolicyData & ScheduleData = {};
  for (const [name, global] of Object.entries(POLICY_SETTINGS)) {
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
  let plex = $derived(settingsState.hasServerType("plex"));

  let arrName = $derived(
    settingsState.current.radarr_configured && settingsState.current.sonarr_configured
      ? "Radarr and Sonarr"
      : settingsState.current.radarr_configured
        ? "Radarr"
        : "Sonarr",
  );
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
  Overture changes a collection only once it is adopted.
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
      maxlength={TEXT_LIMITS.tmdbRegion}
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
    arr={anyArr ? arrName : null}
  >
    {#snippet requests()}
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
    {/snippet}
  </CollectionPolicyFields>
</div>
<h4 class="caps-label">Active dates</h4>
<p class="hint">Collections sync on the Sync schedules under Operations, or with Sync.</p>
<div class="options-col">
  <CollectionScheduleFields {policy} level="global" />
</div>

<style>
  h4 {
    margin: var(--space-2) 0 0;
  }
</style>
