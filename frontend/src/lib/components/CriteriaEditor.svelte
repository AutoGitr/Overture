<script lang="ts">
  import ClipboardPaste from "@lucide/svelte/icons/clipboard-paste";
  import Copy from "@lucide/svelte/icons/copy";
  import CopyPlus from "@lucide/svelte/icons/copy-plus";
  import Plus from "@lucide/svelte/icons/plus";
  import X from "@lucide/svelte/icons/x";
  import type {
    CollectionFieldRead,
    CollectionSourceRead,
    FilterGroupInput,
    MediaType,
  } from "../../generated/rest/types.gen";
  import { criteriaClipboard } from "../stores/criteriaClipboard.svelte";
  import { emptyGroup, fieldCondition } from "../utils/collectionCriteria";
  import CriteriaCondition from "./CriteriaCondition.svelte";
  import CriteriaEditor from "./CriteriaEditor.svelte";

  let {
    group = $bindable(),
    fields,
    sources,
    mediaType,
    libraryId,
    label,
    depth = 0,
    onremove = null,
    onduplicate = null,
  }: {
    group: FilterGroupInput;
    fields: CollectionFieldRead[];
    sources: CollectionSourceRead[];
    mediaType: MediaType;
    libraryId: string;
    /** Names the group for assistive technology, such as "Criteria". */
    label: string;
    depth?: number;
    /** A nested group's own actions; the top group has none. */
    onremove?: (() => void) | null;
    onduplicate?: (() => void) | null;
  } = $props();

  /** Nesting stops here, as adding a group does. */
  const MAX_DEPTH = 3;
  let copied = $derived(criteriaClipboard.copied);
  let pasteBlocker = $derived.by(() => {
    if (!criteriaClipboard.fits({ fields, sources, mediaType }))
      return `These criteria cannot test the copied ${copied?.kind}`;
    if (copied?.kind === "group" && depth >= MAX_DEPTH) return "Groups nest only this deep";
    return null;
  });

  function paste() {
    if (copied?.kind === "condition")
      (group.conditions ??= []).push(structuredClone(copied.condition));
    else if (copied?.kind === "group") (group.groups ??= []).push(structuredClone(copied.group));
  }

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
    {#if onremove && onduplicate}
      <div class="head-actions">
        <button
          type="button"
          class="btn btn-ghost btn-sm btn-icon"
          aria-label={`Copy ${label}`}
          title="Copy group, to paste into any criteria"
          onclick={() => criteriaClipboard.copyGroup(mediaType, group)}><Copy size={14} /></button
        >
        <button
          type="button"
          class="btn btn-ghost btn-sm btn-icon"
          aria-label={`Duplicate ${label}`}
          title="Duplicate group"
          onclick={onduplicate}><CopyPlus size={14} /></button
        >
        <button
          type="button"
          class="btn btn-ghost btn-sm btn-icon"
          aria-label={`Remove ${label}`}
          title="Remove group"
          onclick={onremove}><X size={14} /></button
        >
      </div>
    {/if}
  </div>
  {#each group.conditions ?? [] as condition, index (condition)}
    <CriteriaCondition
      bind:condition={group.conditions![index]!}
      {fields}
      {sources}
      {mediaType}
      {libraryId}
      label={`${label} condition ${index + 1}`}
      onchange={(replacement) => group.conditions?.splice(index, 1, replacement)}
      onduplicate={() =>
        group.conditions?.splice(index + 1, 0, $state.snapshot(condition))}
      oncopy={() => criteriaClipboard.copyCondition(mediaType, condition)}
      onremove={() => group.conditions?.splice(index, 1)}
    />
  {/each}
  {#each group.groups ?? [] as nested, index (nested)}
    <CriteriaEditor
      bind:group={group.groups![index]!}
      {fields}
      {sources}
      {mediaType}
      {libraryId}
      label={`${label} group ${index + 1}`}
      depth={depth + 1}
      onremove={() => group.groups?.splice(index, 1)}
      onduplicate={() =>
        group.groups?.splice(index + 1, 0, $state.snapshot(nested))}
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
    {#if depth < MAX_DEPTH}
      <button
        type="button"
        class="btn btn-ghost btn-sm"
        onclick={() => (group.groups ??= []).push(emptyGroup(group.mode === "all" ? "any" : "all"))}
        ><Plus size={14} /> Group</button
      >
    {/if}
    {#if copied}
      <button
        type="button"
        class="btn btn-ghost btn-sm"
        aria-label={`Paste copied ${copied.kind} into ${label}`}
        disabled={!!pasteBlocker}
        title={pasteBlocker ?? undefined}
        onclick={paste}><ClipboardPaste size={14} /> Paste {copied.kind}</button
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

  .head-actions {
    display: flex;
    gap: 2px;
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
