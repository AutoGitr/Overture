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
  import { BUILDER_KINDS, splitIds, splitList } from "../utils/collectionBuilders";
  import FilterGroupEditor from "./FilterGroupEditor.svelte";

  let {
    builder,
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

  const tagsId = $props.id();

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

  let builderLabel = $derived(BUILDER_KINDS.find((kind) => kind.type === builder.type)?.label);
</script>

{#snippet tagPicker(title: string, tags: { id: number; label: string }[] | undefined)}
  {@const builderTags =
    builder.type === "radarr_tag" || builder.type === "sonarr_tag" ? (builder.tags ?? []) : []}
  <div class="form-label">
    <label for={tagsId}>{title}</label>
    {#if tags && tags.length > 0}
      <div class="tag-chips">
        {#each tags as tag (tag.id)}
          <button
            type="button"
            class={["btn btn-sm", builderTags.includes(tag.label) ? "btn-secondary" : "btn-ghost"]}
            aria-pressed={builderTags.includes(tag.label)}
            onclick={() => toggleTag(tag.label)}
          >
            {tag.label}
          </button>
        {/each}
      </div>
    {/if}
    <input
      id={tagsId}
      type="text"
      placeholder="Tag names separated by comma"
      value={builderTags.join(", ")}
      onchange={(e) => {
        if (builder.type === "radarr_tag" || builder.type === "sonarr_tag") {
          builder.tags = splitList(e.currentTarget.value);
        }
      }}
    />
  </div>
{/snippet}

<div class="builder-card">
  <div class="builder-header">
    <h4 class="builder-title">{builderLabel}</h4>
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
      </label>
      <span class="hint">The numeric ID from themoviedb.org collection URL.</span>
    {:else if builder.type === "tmdb_item"}
      <label class="form-label">
        TMDB {mediaType === "movie" ? "movie" : "show"} IDs
        <textarea
          rows={3}
          placeholder="e.g. 550, 680, 157336"
          value={builder.tmdb_ids.join(", ")}
          onchange={(e) => {
            if (builder.type === "tmdb_item") {
              builder.tmdb_ids = splitIds(e.currentTarget.value);
            }
          }}></textarea>
      </label>
      <span class="hint">Comma-separated or newline-separated TMDB IDs.</span>
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
                builder.person_name = e.currentTarget.value || null;
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
          value={builder.identifiers.join(", ")}
          onchange={(e) => {
            if (builder.type === "mdblist") {
              builder.identifiers = splitList(e.currentTarget.value);
            }
          }}
          placeholder="https://mdblist.com/lists/user/slug or user/slug"
        />
      </label>
      <span class="hint">Paste list URLs or slugs separated by commas.</span>
    {:else if builder.type === "radarr_tag"}
      {@render tagPicker("Radarr tags", radarrTags.data)}
    {:else if builder.type === "sonarr_tag"}
      {@render tagPicker("Sonarr tags", sonarrTags.data)}
    {:else if builder.type === "library_filter"}
      <FilterGroupEditor group={builder.filter_group} label="Library filter group" />
    {/if}
  </div>
</div>

<style>
  .builder-card {
    border: var(--border-subtle);
    border-radius: var(--radius-md);
    padding: var(--space-3);
    background: var(--bg-tertiary);
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }

  .builder-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding-bottom: var(--space-2);
    border-bottom: var(--border-subtle);
  }

  .builder-title {
    margin: 0;
    font-weight: 600;
    font-size: var(--text-sm);
  }

  .builder-actions {
    display: flex;
    gap: var(--space-1);
  }

  .builder-body {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }

  .form-grid {
    display: grid;
    grid-template-columns: 1fr 2fr;
    gap: var(--space-3);
    @media (max-width: 640px) {
      grid-template-columns: 1fr;
    }
  }

  .checkbox-row {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-3);
    padding-top: var(--space-1);
  }

  .checkbox-label {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-size: var(--text-sm);
    cursor: pointer;
  }

  .tag-chips {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-1);
    margin-bottom: var(--space-2);
  }
</style>
