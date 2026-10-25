<script lang="ts">
  import { SvelteSet } from "svelte/reactivity";
  import ArrowDown from "@lucide/svelte/icons/arrow-down";
  import ArrowUp from "@lucide/svelte/icons/arrow-up";
  import Trash2 from "@lucide/svelte/icons/trash-2";
  import { createQuery } from "@tanstack/svelte-query";
  import {
    listRadarrTagsOptions,
    listSonarrTagsOptions,
  } from "../../generated/rest/@tanstack/svelte-query.gen";
  import type {
    CollectionBuilderInput,
    MediaType,
    TmdbPersonRole,
  } from "../../generated/rest/types.gen";
  import { settingsState } from "../stores/settingsState.svelte";
  import { emptyFilterGroup, splitIds, splitList } from "../utils/collectionBuilders";
  import FilterGroupEditor from "./FilterGroupEditor.svelte";

  let {
    builder = $bindable(),
    index = 0,
    total = 1,
    mediaType,
    removable = true,
    onremove,
    onmoveup,
    onmovedown,
  }: {
    builder: CollectionBuilderInput;
    index?: number;
    total?: number;
    mediaType: MediaType;
    removable?: boolean;
    onremove?: () => void;
    onmoveup?: () => void;
    onmovedown?: () => void;
  } = $props();

  const radarrTags = createQuery(() => ({
    ...listRadarrTagsOptions(),
    enabled: builder.type === "radarr_tag" && settingsState.current.radarr_configured,
  }));

  const sonarrTags = createQuery(() => ({
    ...listSonarrTagsOptions(),
    enabled: builder.type === "sonarr_tag" && settingsState.current.sonarr_configured,
  }));

  const roles: readonly { id: TmdbPersonRole; label: string }[] = [
    { id: "actor", label: "Actor / Cast" },
    { id: "director", label: "Director" },
    { id: "writer", label: "Writer" },
    { id: "producer", label: "Producer" },
  ];

  function toggleRole(role: TmdbPersonRole) {
    if (builder.type !== "tmdb_person") return;
    const current = new SvelteSet<TmdbPersonRole>(builder.roles ?? ["actor"]);
    if (current.has(role)) {
      current.delete(role);
    } else {
      current.add(role);
    }
    builder.roles = Array.from(current);
  }

  function toggleTag(tag: string) {
    if (builder.type !== "radarr_tag" && builder.type !== "sonarr_tag") return;
    const current = new SvelteSet<string>(builder.tags ?? []);
    if (current.has(tag)) {
      current.delete(tag);
    } else {
      current.add(tag);
    }
    builder.tags = Array.from(current);
  }

  const builderLabels: Record<CollectionBuilderInput["type"], string> = {
    tmdb_collection: "TMDB Franchise",
    tmdb_item: "TMDB Titles",
    tmdb_person: "TMDB Person Credits",
    mdblist: "MDBList",
    radarr_tag: "Radarr Tags",
    sonarr_tag: "Sonarr Tags",
    library_filter: "Library Filter",
  };
</script>

<div class="builder-card">
  <div class="builder-header">
    <span class="builder-title">{builderLabels[builder.type]}</span>
    <div class="builder-actions">
      {#if onmoveup}
        <button
          type="button"
          class="btn btn-ghost btn-sm btn-icon"
          title="Move builder up"
          disabled={index <= 0}
          onclick={onmoveup}
        >
          <ArrowUp size={14} />
        </button>
      {/if}
      {#if onmovedown}
        <button
          type="button"
          class="btn btn-ghost btn-sm btn-icon"
          title="Move builder down"
          disabled={index >= total - 1}
          onclick={onmovedown}
        >
          <ArrowDown size={14} />
        </button>
      {/if}
      {#if removable && onremove}
        <button
          type="button"
          class="btn btn-ghost btn-sm btn-icon text-danger"
          title="Remove builder"
          onclick={onremove}
        >
          <Trash2 size={14} />
        </button>
      {/if}
    </div>
  </div>

  <div class="builder-body">
    {#if builder.type === "tmdb_collection"}
      <label class="form-label">
        TMDB franchise ID
        <input
          type="number"
          min="1"
          required
          value={builder.collection_id || ""}
          oninput={(e) => {
            if (builder.type === "tmdb_collection") {
              builder.collection_id = e.currentTarget.valueAsNumber || 0;
            }
          }}
        />
        <span class="hint">The numeric ID from themoviedb.org collection URL.</span>
      </label>
    {:else if builder.type === "tmdb_item"}
      <label class="form-label">
        TMDB {mediaType === "movie" ? "movie" : "show"} IDs
        <textarea
          rows={3}
          placeholder="e.g. 550, 680, 157336"
          value={builder.tmdb_ids.join(", ")}
          oninput={(e) => {
            if (builder.type === "tmdb_item") {
              builder.tmdb_ids = splitIds(e.currentTarget.value);
            }
          }}></textarea>
        <span class="hint">Comma-separated or newline-separated TMDB IDs.</span>
      </label>
    {:else if builder.type === "tmdb_person"}
      <div class="form-grid">
        <label class="form-label">
          Person ID
          <input
            type="number"
            min="1"
            required
            value={builder.person_id || ""}
            oninput={(e) => {
              if (builder.type === "tmdb_person") {
                builder.person_id = e.currentTarget.valueAsNumber || 0;
              }
            }}
          />
        </label>
        <label class="form-label">
          Name (optional)
          <input
            type="text"
            placeholder="e.g. Quentin Tarantino"
            value={builder.person_name ?? ""}
            oninput={(e) => {
              if (builder.type === "tmdb_person") {
                builder.person_name = e.currentTarget.value.trim() || null;
              }
            }}
          />
        </label>
      </div>

      <div class="form-label">
        <span>Credits to include</span>
        <div class="checkbox-row">
          {#each roles as role (role.id)}
            <label class="checkbox-label">
              <input
                type="checkbox"
                checked={(builder.roles ?? ["actor"]).includes(role.id)}
                onchange={() => toggleRole(role.id)}
              />
              {role.label}
            </label>
          {/each}
        </div>
      </div>

      <label class="form-row">
        <input
          type="checkbox"
          checked={builder.use_biography ?? false}
          onchange={(e) => {
            if (builder.type === "tmdb_person") {
              builder.use_biography = e.currentTarget.checked;
            }
          }}
        />
        Use person biography as collection summary
      </label>
    {:else if builder.type === "mdblist"}
      <label class="form-label">
        MDBList list URL or ID
        <input
          required
          value={builder.identifiers[0] ?? ""}
          oninput={(e) => {
            if (builder.type === "mdblist") {
              builder.identifiers = splitList(e.currentTarget.value);
            }
          }}
          placeholder="https://mdblist.com/lists/user/slug or user/slug"
        />
        <span class="hint">Paste list URLs or slugs separated by commas.</span>
      </label>
    {:else if builder.type === "radarr_tag"}
      <div class="form-label">
        <span>Radarr tags</span>
        {#if radarrTags.data && radarrTags.data.length > 0}
          <div class="tag-chips">
            {#each radarrTags.data as tag (tag.id)}
              <button
                type="button"
                class="tag-chip"
                class:active={(builder.tags ?? []).includes(tag.label)}
                onclick={() => toggleTag(tag.label)}
              >
                {tag.label}
              </button>
            {/each}
          </div>
        {/if}
        <input
          type="text"
          placeholder="Tag names separated by comma"
          value={(builder.tags ?? []).join(", ")}
          oninput={(e) => {
            if (builder.type === "radarr_tag") {
              builder.tags = splitList(e.currentTarget.value);
            }
          }}
        />
      </div>
    {:else if builder.type === "sonarr_tag"}
      <div class="form-label">
        <span>Sonarr tags</span>
        {#if sonarrTags.data && sonarrTags.data.length > 0}
          <div class="tag-chips">
            {#each sonarrTags.data as tag (tag.id)}
              <button
                type="button"
                class="tag-chip"
                class:active={(builder.tags ?? []).includes(tag.label)}
                onclick={() => toggleTag(tag.label)}
              >
                {tag.label}
              </button>
            {/each}
          </div>
        {/if}
        <input
          type="text"
          placeholder="Tag names separated by comma"
          value={(builder.tags ?? []).join(", ")}
          oninput={(e) => {
            if (builder.type === "sonarr_tag") {
              builder.tags = splitList(e.currentTarget.value);
            }
          }}
        />
      </div>
    {:else if builder.type === "library_filter"}
      {#if !builder.filter_group}
        {((builder.filter_group = emptyFilterGroup()), "")}
      {/if}
      <FilterGroupEditor bind:group={builder.filter_group} label="Library filter group" />
    {/if}
  </div>
</div>

<style>
  .builder-card {
    border: 1px solid var(--border-color, #333);
    border-radius: var(--radius-md, 6px);
    padding: var(--space-3, 0.75rem);
    background: var(--bg-surface-secondary, rgba(255, 255, 255, 0.03));
    display: flex;
    flex-direction: column;
    gap: var(--space-3, 0.75rem);
  }

  .builder-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding-bottom: var(--space-2, 0.5rem);
    border-bottom: 1px solid var(--border-color, #333);
  }

  .builder-title {
    font-weight: var(--font-semibold, 600);
    font-size: var(--text-sm, 0.875rem);
  }

  .builder-actions {
    display: flex;
    gap: var(--space-1, 0.25rem);
  }

  .builder-body {
    display: flex;
    flex-direction: column;
    gap: var(--space-3, 0.75rem);
  }

  .form-grid {
    display: grid;
    grid-template-columns: 1fr 2fr;
    gap: var(--space-3, 0.75rem);
  }

  .checkbox-row {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-3, 0.75rem);
    padding-top: var(--space-1, 0.25rem);
  }

  .checkbox-label {
    display: flex;
    align-items: center;
    gap: var(--space-2, 0.5rem);
    font-size: var(--text-sm, 0.875rem);
    cursor: pointer;
  }

  .tag-chips {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-1, 0.25rem);
    margin-bottom: var(--space-2, 0.5rem);
  }

  .tag-chip {
    background: var(--bg-surface-tertiary, rgba(255, 255, 255, 0.08));
    border: 1px solid var(--border-color, #444);
    border-radius: var(--radius-full, 9999px);
    padding: 0.15rem 0.6rem;
    font-size: var(--text-xs, 0.75rem);
    cursor: pointer;
    color: var(--text-muted, #aaa);
    transition: all 0.15s ease;
  }

  .tag-chip.active {
    background: var(--color-primary, #6366f1);
    border-color: var(--color-primary, #6366f1);
    color: #fff;
  }
</style>
