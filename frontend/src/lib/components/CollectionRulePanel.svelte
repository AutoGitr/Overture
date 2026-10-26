<script lang="ts">
  import Plus from "@lucide/svelte/icons/plus";
  import type { CollectionBuilderInput, SmartSortOrder } from "../../generated/rest/types.gen";
  import { BUILDER_KINDS, newBuilder } from "../utils/collectionBuilders";
  import { CollectionEditor, type CollectionDraft } from "../utils/collectionForms.svelte";
  import CollectionBuilderItem from "./CollectionBuilderItem.svelte";
  import DetailForm from "./DetailForm.svelte";
  import CollectionPolicyFields from "./CollectionPolicyFields.svelte";
  import FilterGroupEditor from "./FilterGroupEditor.svelte";

  let { editor }: { editor: CollectionEditor | CollectionDraft } = $props();

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

{#if editor.sourceType !== "unmanaged"}
  <DetailForm
    collapsible
    expanded
    title="Content"
    description={editor.sourceType === "smart"
      ? "Plex smart collections automatically evaluate filter rules directly on your Plex media server."
      : "Combine sources in order. Results are merged without duplicates; library filters add matching items rather than narrowing other sources."}
    busy={editor.busy}
  >
    {#if editor.sourceType === "smart"}
      {#if editor instanceof CollectionEditor && editor.collection.kind === "smart" && !editor.existingRule}
        <div class="form-wide">
          <p class="hint">
            This collection's smart filter is managed in Plex. Enable editing to replace it with
            rules defined here. Display changes keep the existing filter.
          </p>
          <label class="form-row">
            <input type="checkbox" bind:checked={editor.manageSmartFilter} />
            Manage smart filter in Overture
          </label>
        </div>
      {/if}
      {#if editor.smartFilterEditable && editor.rule.smart_filter}
        <div class="smart-section form-wide">
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
              oninput={(e) => (editor.rule.managed_label = e.currentTarget.value || null)}
            />
            <span class="hint">
              With sources below, Overture labels their results and Plex filters those items.
              Without sources, enter an existing library label or leave this blank.
            </span>
          </label>

          {#if editor.rule.smart_filter.filter_group}
            <FilterGroupEditor
              group={editor.rule.smart_filter.filter_group}
              label="Smart collection criteria"
            />
          {/if}
        </div>
      {/if}
    {/if}
    {#if editor.smartFilterEditable && (editor.sourceType === "builders" || editor.rule.managed_label || editor.rule.builders?.length)}
      <div class="builders-stack form-wide">
        {#each editor.rule.builders ?? [] as _builder, i (i)}
          {#if editor.rule.builders && editor.rule.builders[i]}
            <CollectionBuilderItem
              builder={editor.rule.builders[i]}
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
          <span class="hint"
            >{editor.sourceType === "smart"
              ? "Optional sources for the managed Plex label:"
              : "Add a source:"}</span
          >
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
    {/if}
    {#if editor.sourceType === "builders"}
      <CollectionPolicyFields policy={editor.rule} defaults={editor.defaults.data} section="sync" />
    {/if}
  </DetailForm>
{/if}

<style>
  .smart-section,
  .builders-stack {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
  }
  .form-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: var(--space-4);
    @media (max-width: 640px) {
      grid-template-columns: 1fr;
    }
  }
  .add-builder-row {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-3);
    background: var(--bg-tertiary);
    border-radius: var(--radius-md);
  }
  .builder-buttons {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
  }
</style>
