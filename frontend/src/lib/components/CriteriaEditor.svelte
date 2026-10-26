<script lang="ts">
  import Plus from "@lucide/svelte/icons/plus";
  import X from "@lucide/svelte/icons/x";
  import type {
    CollectionFieldRead,
    CollectionSourceRead,
    FilterGroupInput,
    MediaType,
  } from "../../generated/rest/types.gen";
  import { emptyGroup, fieldCondition } from "../utils/collectionCriteria";
  import CriteriaCondition from "./CriteriaCondition.svelte";
  import CriteriaEditor from "./CriteriaEditor.svelte";

  let {
    group,
    fields,
    sources,
    mediaType,
    libraryId,
    label,
    depth = 0,
    onremove = null,
  }: {
    group: FilterGroupInput;
    fields: CollectionFieldRead[];
    sources: CollectionSourceRead[];
    mediaType: MediaType;
    libraryId: string;
    /** Names the group for assistive technology, such as "Criteria". */
    label: string;
    depth?: number;
    onremove?: (() => void) | null;
  } = $props();

  function addCondition() {
    const first = fields[0];
    if (first) (group.conditions ??= []).push(fieldCondition(first));
  }
</script>

<fieldset class={["group", { nested: depth > 0 }]}>
  <legend class="sr-only">{label}</legend>
  <div class="head">
    <label class="mode"
      >Match
      <select bind:value={group.mode} aria-label={`${label} match`}>
        <option value="all">all</option>
        <option value="any">any</option>
      </select>
      of the following</label
    >
    {#if onremove}
      <button
        type="button"
        class="btn btn-ghost btn-sm btn-icon"
        aria-label={`Remove ${label}`}
        title="Remove group"
        onclick={onremove}><X size={14} /></button
      >
    {/if}
  </div>
  {#each group.conditions ?? [] as condition, index (condition)}
    <CriteriaCondition
      {condition}
      {fields}
      {sources}
      {mediaType}
      {libraryId}
      label={`${label} condition ${index + 1}`}
      onchange={(replacement) => group.conditions?.splice(index, 1, replacement)}
      onremove={() => group.conditions?.splice(index, 1)}
    />
  {/each}
  {#each group.groups ?? [] as nested, index (nested)}
    <CriteriaEditor
      group={nested}
      {fields}
      {sources}
      {mediaType}
      {libraryId}
      label={`${label} group ${index + 1}`}
      depth={depth + 1}
      onremove={() => group.groups?.splice(index, 1)}
    />
  {/each}
  {#if !group.conditions?.length && !group.groups?.length}
    <p class="hint">No conditions yet.</p>
  {/if}
  <div class="actions">
    <button
      type="button"
      class="btn btn-ghost btn-sm"
      disabled={!fields.length}
      onclick={addCondition}><Plus size={14} /> Condition</button
    >
    {#if depth < 3}
      <button
        type="button"
        class="btn btn-ghost btn-sm"
        onclick={() => (group.groups ??= []).push(emptyGroup(group.mode === "all" ? "any" : "all"))}
        ><Plus size={14} /> Group</button
      >
    {/if}
  </div>
</fieldset>

<style>
  .group {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    min-width: 0;
    margin: 0;
    padding: var(--space-3);
    border: var(--border-subtle);
    border-radius: var(--radius-md);
  }

  .nested {
    background: var(--bg-tertiary);
  }

  .head,
  .actions {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
  }

  .actions {
    justify-content: flex-start;
  }

  .mode {
    display: inline-flex;
    flex-wrap: wrap;
    align-items: center;
    gap: var(--space-2);
    font-size: var(--text-sm);
  }

  .mode select {
    width: auto;
  }
</style>
