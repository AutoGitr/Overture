<script lang="ts">
  import Plus from "@lucide/svelte/icons/plus";
  import type { CollectionBuilderInput, SmartSortOrder } from "../../generated/rest/types.gen";
  import {
    BUILDER_KINDS,
    emptyFilterGroup,
    emptySmartFilter,
    newBuilder,
    splitList,
  } from "../utils/collectionBuilders";
  import type {
    CollectionEditor,
    CollectionDraft,
    RuleEditorSource,
  } from "../utils/collectionForms.svelte";
  import CollectionBuilderItem from "./CollectionBuilderItem.svelte";
  import CollectionPolicyFields from "./CollectionPolicyFields.svelte";
  import DetailForm from "./DetailForm.svelte";
  import FilterGroupEditor from "./FilterGroupEditor.svelte";

  let { editor = $bindable() }: { editor: CollectionEditor | CollectionDraft } = $props();

  let filters = $derived(editor.rule.filters ?? {});
  let isPlex = $derived(editor.serverType === "plex");

  const sortOrders: readonly { id: SmartSortOrder; label: string }[] = [
    { id: "release.desc", label: "Release date (newest first)" },
    { id: "release.asc", label: "Release date (oldest first)" },
    { id: "title.asc", label: "Title (A to Z)" },
    { id: "title.desc", label: "Title (Z to A)" },
    { id: "added.desc", label: "Date added (newest first)" },
    { id: "added.asc", label: "Date added (oldest first)" },
    { id: "critic_rating.desc", label: "Critic rating (highest first)" },
    { id: "audience_rating.desc", label: "Audience rating (highest first)" },
    { id: "rating.desc", label: "Rating (highest first)" },
    { id: "plays.desc", label: "Play count (most played)" },
    { id: "duration.desc", label: "Duration (longest first)" },
    { id: "duration.asc", label: "Duration (shortest first)" },
    { id: "random", label: "Random" },
  ];

  function onSourceChange(value: string) {
    editor.sourceType = value as RuleEditorSource;
    if (value === "smart") {
      editor.kind = "smart";
      if (!editor.rule.smart_filter) {
        editor.rule.smart_filter = emptySmartFilter();
      }
    } else {
      if (editor.kind === "smart") {
        editor.kind = "regular";
      }
      if (value === "composite") {
        if (!editor.rule.builders || editor.rule.builders.length === 0) {
          editor.rule.builders = [
            newBuilder(editor.mediaType === "movie" ? "tmdb_collection" : "mdblist"),
          ];
        }
      } else if (value === "mdblist") {
        editor.rule.source_identifier = editor.rule.source_identifier || "";
        editor.rule.builders = [
          { type: "mdblist", identifiers: splitList(editor.rule.source_identifier) },
        ];
      } else if (value === "tmdb") {
        editor.rule.source_identifier = editor.rule.source_identifier || "";
        editor.rule.builders = [
          { type: "tmdb_collection", collection_id: Number(editor.rule.source_identifier) || 0 },
        ];
      }
    }
  }

  function addBuilder(type: CollectionBuilderInput["type"]) {
    if (!editor.rule.builders) {
      editor.rule.builders = [];
    }
    editor.rule.builders.push(newBuilder(type));
    editor.sourceType = "composite";
  }

  function removeBuilder(index: number) {
    if (!editor.rule.builders) return;
    editor.rule.builders.splice(index, 1);
  }

  function moveBuilder(fromIndex: number, toIndex: number) {
    if (!editor.rule.builders) return;
    if (toIndex < 0 || toIndex >= editor.rule.builders.length) return;
    const [item] = editor.rule.builders.splice(fromIndex, 1);
    if (item) {
      editor.rule.builders.splice(toIndex, 0, item);
    }
  }
</script>

<DetailForm
  title="Builder & Dynamic Rules Engine"
  description="Build this collection from external lists, metadata builders, or library filters, then keep it in sync."
  busy={editor.busy}
>
  <label class="form-label">
    Source
    <select value={editor.sourceType} onchange={(e) => onSourceChange(e.currentTarget.value)}>
      <option value="manual">Manual</option>
      <option value="mdblist">MDBList</option>
      {#if editor.mediaType === "movie"}
        <option value="tmdb">TMDB franchise</option>
      {/if}
      <option value="filter">Library filter</option>
      <option value="composite">Multi-source builders</option>
      {#if isPlex}
        <option value="smart">Plex smart collection</option>
      {/if}
    </select>
  </label>

  {#if editor.sourceType !== "manual"}
    {#if editor.sourceType === "smart"}
      {#if !editor.rule.smart_filter}
        {((editor.rule.smart_filter = emptySmartFilter()), "")}
      {/if}
      {#if editor.rule.smart_filter}
        <div class="smart-section">
          <p class="hint">
            Plex smart collections automatically evaluate filter rules directly on your Plex media
            server.
          </p>

          <div class="form-grid">
            <label class="form-label">
              Smart sort order
              <select bind:value={editor.rule.smart_filter.sort_by}>
                {#each sortOrders as order (order.id)}
                  <option value={order.id}>{order.label}</option>
                {/each}
              </select>
            </label>

            <label class="form-label">
              Item limit
              <input
                type="number"
                min="1"
                placeholder="Unlimited"
                value={editor.rule.smart_filter.limit ?? ""}
                oninput={(e) => {
                  if (editor.rule.smart_filter) {
                    editor.rule.smart_filter.limit = e.currentTarget.value
                      ? e.currentTarget.valueAsNumber
                      : null;
                  }
                }}
              />
            </label>
          </div>

          <label class="form-label">
            Managed Plex label
            <input
              placeholder="e.g. Marvel Cinematic Universe"
              maxlength="100"
              value={editor.rule.managed_label ?? ""}
              oninput={(e) => (editor.rule.managed_label = e.currentTarget.value.trim() || null)}
            />
            <span class="hint">
              Optional label synced to matching items on Plex and included in smart filter criteria.
            </span>
          </label>

          {#if !editor.rule.smart_filter.filter_group}
            {((editor.rule.smart_filter.filter_group = emptyFilterGroup()), "")}
          {/if}
          {#if editor.rule.smart_filter.filter_group}
            <FilterGroupEditor
              bind:group={editor.rule.smart_filter.filter_group}
              label="Smart collection criteria"
            />
          {/if}
        </div>
      {/if}
    {:else if editor.sourceType === "composite"}
      <div class="builders-stack">
        {#each editor.rule.builders ?? [] as _builder, i (i)}
          {#if editor.rule.builders && editor.rule.builders[i]}
            <CollectionBuilderItem
              bind:builder={editor.rule.builders[i]}
              index={i}
              total={editor.rule.builders.length}
              mediaType={editor.mediaType}
              onremove={() => removeBuilder(i)}
              onmoveup={() => moveBuilder(i, i - 1)}
              onmovedown={() => moveBuilder(i, i + 1)}
            />
          {/if}
        {/each}

        <div class="add-builder-row">
          <span class="hint">Add a source builder:</span>
          <div class="builder-buttons">
            {#each BUILDER_KINDS as kind (kind.type)}
              {#if !kind.media || kind.media === editor.mediaType}
                <button
                  type="button"
                  class="btn btn-ghost btn-sm"
                  onclick={() => addBuilder(kind.type)}
                >
                  <Plus size={14} />
                  {kind.label}
                </button>
              {/if}
            {/each}
          </div>
        </div>
      </div>
    {:else if editor.sourceType === "filter"}
      <label class="form-label">
        Decade
        <input
          type="number"
          min="1800"
          max="3000"
          step="10"
          value={filters.decade ?? ""}
          oninput={(event) =>
            (editor.rule.filters = {
              ...filters,
              decade: event.currentTarget.value ? event.currentTarget.valueAsNumber : null,
            })}
        />
      </label>
      <label class="form-label">
        Studio
        <input
          value={filters.studio ?? ""}
          oninput={(event) =>
            (editor.rule.filters = { ...filters, studio: event.currentTarget.value || null })}
        />
      </label>
      <label class="form-label">
        Genre
        <input
          value={filters.genre ?? ""}
          oninput={(event) =>
            (editor.rule.filters = { ...filters, genre: event.currentTarget.value || null })}
        />
      </label>
      <div class="form-wide">
        <button
          type="button"
          class="btn btn-ghost btn-sm"
          onclick={() => (editor.sourceType = "composite")}
        >
          <Plus size={14} />
          Switch to composable filter tree &amp; multi-source builders
        </button>
      </div>
    {:else}
      <label class="form-label">
        {editor.sourceType === "mdblist" ? "MDBList list URL or ID" : "TMDB franchise ID"}
        <input
          required
          bind:value={editor.rule.source_identifier}
          oninput={(e) => {
            if (editor.sourceType === "mdblist") {
              editor.rule.builders = [
                { type: "mdblist", identifiers: splitList(e.currentTarget.value) },
              ];
            } else if (editor.sourceType === "tmdb") {
              editor.rule.builders = [
                { type: "tmdb_collection", collection_id: Number(e.currentTarget.value) || 0 },
              ];
            }
          }}
        />
      </label>
      <div class="form-wide">
        <button
          type="button"
          class="btn btn-ghost btn-sm"
          onclick={() => {
            if (editor.sourceType === "mdblist") {
              editor.rule.builders = [
                { type: "mdblist", identifiers: splitList(editor.rule.source_identifier ?? "") },
              ];
            } else if (editor.sourceType === "tmdb") {
              editor.rule.builders = [
                {
                  type: "tmdb_collection",
                  collection_id: Number(editor.rule.source_identifier) || 0,
                },
              ];
            }
            editor.sourceType = "composite";
          }}
        >
          <Plus size={14} />
          Add another source (combine with other builders)
        </button>
      </div>
    {/if}

    <CollectionPolicyFields policy={editor.rule} plex={isPlex} />

    <div class="seasonal-row">
      <label class="form-label">
        Rule active start (MM-DD)
        <input
          placeholder="12-15"
          maxlength="5"
          value={editor.rule.active_start_mmdd ?? ""}
          oninput={(e) => (editor.rule.active_start_mmdd = e.currentTarget.value.trim() || null)}
        />
      </label>
      <label class="form-label">
        Rule active end (MM-DD)
        <input
          placeholder="01-05"
          maxlength="5"
          value={editor.rule.active_end_mmdd ?? ""}
          oninput={(e) => (editor.rule.active_end_mmdd = e.currentTarget.value.trim() || null)}
        />
      </label>
    </div>

    <label class="form-label">
      Rule summary template
      <input
        maxlength="500"
        placeholder="&#123;title&#125; - &#123;summary&#125;"
        value={editor.rule.summary_format ?? ""}
        oninput={(e) => (editor.rule.summary_format = e.currentTarget.value.trim() || null)}
      />
      <span class="hint">
        Tokens: &#123;title&#125;, &#123;group&#125;, &#123;start_date&#125;, &#123;end_date&#125;,
        &#123;summary&#125;.
      </span>
    </label>

    <label class="form-label">
      Sync interval (hours)
      <input
        type="number"
        min="1"
        max="8760"
        required
        bind:value={editor.rule.sync_interval_hours}
      />
    </label>

    <label class="form-row">
      <input type="checkbox" bind:checked={editor.rule.enabled} />
      Enable scheduled sync
    </label>

    {#if editor.existingRule}
      <div class="form-wide options-col">
        <p class="hint">Last run: {editor.existingRule.last_synced_at ?? "Never"}</p>
        {#if editor.existingRule.last_error}
          <p role="alert" class="text-danger">
            {editor.existingRule.last_error}
          </p>
        {/if}
      </div>
    {/if}
  {/if}
</DetailForm>

<style>
  .smart-section {
    display: flex;
    flex-direction: column;
    gap: var(--space-3, 0.75rem);
    border: 1px solid var(--border-color, #333);
    border-radius: var(--radius-md, 6px);
    padding: var(--space-3, 0.75rem);
    background: var(--bg-surface-secondary, rgba(255, 255, 255, 0.03));
  }

  .form-grid {
    display: grid;
    grid-template-columns: 2fr 1fr;
    gap: var(--space-3, 0.75rem);
  }

  .builders-stack {
    display: flex;
    flex-direction: column;
    gap: var(--space-3, 0.75rem);
  }

  .add-builder-row {
    display: flex;
    flex-direction: column;
    gap: var(--space-2, 0.5rem);
    padding: var(--space-2, 0.5rem) 0;
  }

  .builder-buttons {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2, 0.5rem);
  }

  .seasonal-row {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--space-3, 0.75rem);
  }
</style>
