<script lang="ts">
  import { createQuery } from "@tanstack/svelte-query";
  import {
    listRadarrTagsOptions,
    listSonarrTagsOptions,
  } from "../../generated/rest/@tanstack/svelte-query.gen";
  import type {
    CollectionSourceInput,
    MediaType,
    TmdbPersonRole,
  } from "../../generated/rest/types.gen";
  import { splitIds, splitList } from "../utils/collectionCriteria";
  import { toggleSelectedValue } from "../utils/popupSelection";
  import TmdbSourcePicker from "./TmdbSourcePicker.svelte";

  let {
    source,
    mediaType,
    label,
  }: {
    source: CollectionSourceInput;
    mediaType: MediaType;
    /** Names the condition the inputs belong to, for assistive technology. */
    label: string;
  } = $props();

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

  const ROLES: readonly (readonly [TmdbPersonRole, string])[] = [
    ["actor", "Actor"],
    ["director", "Director"],
    ["writer", "Writer"],
    ["producer", "Producer"],
  ];
</script>

<div class="source-fields">
  {#if source.type === "tmdb_collection"}
    <TmdbSourcePicker
      kind="franchise"
      label={`${label} franchise`}
      onpick={(id) => {
        if (source.type === "tmdb_collection") source.collection_id = id;
      }}
    />
    <input
      type="number"
      min="1"
      required
      aria-label={`${label} TMDB franchise ID`}
      placeholder="TMDB franchise ID, e.g. 10"
      value={source.collection_id || ""}
      oninput={(event) => {
        if (source.type === "tmdb_collection")
          source.collection_id = event.currentTarget.valueAsNumber || 0;
      }}
    />
  {:else if source.type === "tmdb_list"}
    <input
      required
      aria-label={`${label} TMDB list IDs`}
      placeholder="TMDB list IDs, e.g. 123, 456"
      value={source.list_ids.join(", ")}
      onchange={(event) => {
        if (source.type === "tmdb_list") source.list_ids = splitIds(event.currentTarget.value);
      }}
    />
  {:else if source.type === "tmdb_item"}
    <input
      required
      aria-label={`${label} TMDB IDs`}
      placeholder={`TMDB ${mediaType === "movie" ? "movie" : "show"} IDs, e.g. 550, 680`}
      value={source.tmdb_ids.join(", ")}
      onchange={(event) => {
        if (source.type === "tmdb_item") source.tmdb_ids = splitIds(event.currentTarget.value);
      }}
    />
  {:else if source.type === "tmdb_person"}
    <TmdbSourcePicker
      kind="person"
      label={`${label} person`}
      onpick={(id, name) => {
        if (source.type !== "tmdb_person") return;
        source.person_id = id;
        source.person_name = name;
      }}
    />
    <div class="row">
      <input
        type="number"
        min="1"
        required
        aria-label={`${label} TMDB person ID`}
        placeholder="TMDB person ID"
        value={source.person_id || ""}
        oninput={(event) => {
          if (source.type === "tmdb_person")
            source.person_id = event.currentTarget.valueAsNumber || 0;
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
    </div>
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
      <label class="check">
        <input
          type="checkbox"
          checked={source.use_biography ?? false}
          onchange={(event) => {
            if (source.type === "tmdb_person") source.use_biography = event.currentTarget.checked;
          }}
        />
        Biography as summary
      </label>
    </div>
  {:else if source.type === "mdblist"}
    <input
      required
      aria-label={`${label} MDBList lists`}
      placeholder="MDBList URLs or user/list, separated by commas"
      value={source.identifiers.join(", ")}
      onchange={(event) => {
        if (source.type === "mdblist") source.identifiers = splitList(event.currentTarget.value);
      }}
    />
  {:else}
    {@const selected = source.tags}
    {#if tags?.length}
      <div class="checks" role="group" aria-label={`${label} tags`}>
        {#each tags as tag (tag.id)}
          <button
            type="button"
            class={["btn btn-sm", selected.includes(tag.label) ? "btn-secondary" : "btn-ghost"]}
            aria-pressed={selected.includes(tag.label)}
            onclick={() => {
              if (source.type === "radarr_tag" || source.type === "sonarr_tag")
                source.tags = toggleSelectedValue(source.tags, tag.label);
            }}>{tag.label}</button
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
  .source-fields,
  .row {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    min-width: 0;
  }

  .row {
    flex-direction: row;
    @media (max-width: 640px) {
      flex-direction: column;
    }
  }

  .row > input {
    flex: 1;
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
