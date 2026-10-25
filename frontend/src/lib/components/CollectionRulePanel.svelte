<script lang="ts">
  import Plus from "@lucide/svelte/icons/plus";
  import type { CollectionBuilderInput, SmartSortOrder } from "../../generated/rest/types.gen";
  import {
    BUILDER_KINDS,
    emptyFilterGroup,
    emptySmartFilter,
    newBuilder,
  } from "../utils/collectionBuilders";
  import type { CollectionEditor, CollectionDraft } from "../utils/collectionForms.svelte";
  import CollectionBuilderItem from "./CollectionBuilderItem.svelte";
  import DetailForm from "./DetailForm.svelte";
  import FilterGroupEditor from "./FilterGroupEditor.svelte";

  let { editor = $bindable() }: { editor: CollectionEditor | CollectionDraft } = $props();

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

  function addBuilder(type: CollectionBuilderInput["type"]) {
    editor.rule.builders = [...(editor.rule.builders ?? []), newBuilder(type)];
  }

  function removeBuilder(index: number) {
    if (!editor.rule.builders) return;
    editor.rule.builders = editor.rule.builders.filter((_, i) => i !== index);
  }

  function moveBuilder(fromIndex: number, toIndex: number) {
    if (!editor.rule.builders) return;
    if (toIndex < 0 || toIndex >= editor.rule.builders.length) return;
    const next = [...editor.rule.builders];
    const [item] = next.splice(fromIndex, 1);
    if (item) {
      next.splice(toIndex, 0, item);
      editor.rule.builders = next;
    }
  }
</script>

{#if editor.sourceType !== "manual"}
  <DetailForm
    title="Content & Sync Rules"
    description={editor.sourceType === "smart"
      ? "Plex smart collections automatically evaluate filter rules directly on your Plex media server."
      : "Compose multiple source builders to dynamically populate this collection."}
    busy={editor.busy}
  >
    {#if editor.sourceType === "smart"}
      {#if !editor.rule.smart_filter}
        {((editor.rule.smart_filter = emptySmartFilter()), "")}
      {/if}
      {#if editor.rule.smart_filter}
        <div class="smart-section">
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
    {:else}
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

      <div class="builder-policy-grid">
        <label class="form-label">
          Sync strategy
          <select bind:value={editor.rule.sync_mode}>
            <option value={null}>Inherit default</option>
            <option value="sync">Strict sync (replaces members)</option>
            <option value="append">Append (keeps manual members)</option>
          </select>
        </label>

        <label class="form-label">
          Minimum members (blank inherits)
          <input
            type="number"
            min="1"
            max="100"
            value={editor.rule.minimum_items ?? ""}
            oninput={(event) =>
              (editor.rule.minimum_items = event.currentTarget.value
                ? event.currentTarget.valueAsNumber
                : null)}
          />
        </label>

        <label class="form-label">
          Below minimum
          <select bind:value={editor.rule.delete_below_minimum}>
            <option value={null}>Inherit default</option>
            <option value={true}>Delete collection</option>
            <option value={false}>Keep collection</option>
          </select>
        </label>

        <label class="form-label">
          Automatic artwork
          <select bind:value={editor.rule.auto_match_art}>
            <option value={null}>Inherit default</option>
            <option value={true}>Enabled</option>
            <option value={false}>Disabled</option>
          </select>
        </label>

        <label class="form-label">
          Automatic themes
          <select bind:value={editor.rule.auto_match_theme}>
            <option value={null}>Inherit default</option>
            <option value={true}>Enabled</option>
            <option value={false}>Disabled</option>
          </select>
        </label>
      </div>
    {/if}

    <div class="sync-row form-wide">
      <label class="form-label">
        Sync interval (hours)
        <input type="number" min="1" max="720" bind:value={editor.rule.sync_interval_hours} />
      </label>
      <label class="form-row">
        <input type="checkbox" bind:checked={editor.rule.enabled} />
        Enable scheduled sync
      </label>
    </div>
  </DetailForm>
{/if}

<style>
  .smart-section {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
  }
  .form-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--space-4);
  }
  .builders-stack {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
  .add-builder-row {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-3);
    background: var(--surface-2);
    border-radius: var(--radius-md);
  }
  .builder-buttons {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
  }
  .builder-policy-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--space-4);
    margin-top: var(--space-3);
  }
  .sync-row {
    display: flex;
    align-items: flex-end;
    gap: var(--space-6);
    margin-top: var(--space-3);
  }
  @media (max-width: 640px) {
    .form-grid,
    .builder-policy-grid,
    .sync-row {
      grid-template-columns: 1fr;
      flex-direction: column;
      align-items: stretch;
    }
  }
</style>
