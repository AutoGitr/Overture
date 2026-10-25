<script lang="ts">
  import Plus from "@lucide/svelte/icons/plus";
  import X from "@lucide/svelte/icons/x";
  import type {
    FilterConditionInput,
    FilterField,
    FilterGroupInput,
    FilterOperator,
  } from "../../generated/rest/types.gen";
  import FilterGroupEditor from "./FilterGroupEditor.svelte";

  let {
    group,
    label,
    depth = 0,
    onremove = null,
  }: {
    group: FilterGroupInput;
    /** Names the group for assistive technology, such as "Filter" or "Smart filter". */
    label: string;
    depth?: number;
    onremove?: (() => void) | null;
  } = $props();

  const TEXT: FilterOperator[] = ["is", "is_not", "contains", "does_not_contain", "starts_with"];
  const NUMBER: FilterOperator[] = ["is", "is_not", "gte", "lte"];
  const FIELDS: Record<FilterField, { label: string; kind: "text" | "number" | "flag" }> = {
    title: { label: "Title", kind: "text" },
    genre: { label: "Genre", kind: "text" },
    studio: { label: "Studio", kind: "text" },
    actor: { label: "Actor", kind: "text" },
    director: { label: "Director", kind: "text" },
    writer: { label: "Writer", kind: "text" },
    producer: { label: "Producer", kind: "text" },
    country: { label: "Country", kind: "text" },
    label: { label: "Label", kind: "text" },
    tag: { label: "Tag", kind: "text" },
    content_rating: { label: "Content rating", kind: "text" },
    resolution: { label: "Resolution", kind: "text" },
    audio_language: { label: "Audio language", kind: "text" },
    year: { label: "Year", kind: "number" },
    decade: { label: "Decade", kind: "number" },
    rating: { label: "Rating", kind: "number" },
    duration_minutes: { label: "Duration (minutes)", kind: "number" },
    unplayed: { label: "Unplayed", kind: "flag" },
    in_progress: { label: "In progress", kind: "flag" },
    added_within_days: { label: "Added within (days)", kind: "number" },
    released_within_days: { label: "Released within (days)", kind: "number" },
  };
  const OPERATOR_LABELS: Record<FilterOperator, string> = {
    is: "is",
    is_not: "is not",
    contains: "contains",
    does_not_contain: "does not contain",
    starts_with: "starts with",
    gte: "at least",
    lte: "at most",
  };

  function operators(field: FilterField): FilterOperator[] {
    const kind = FIELDS[field].kind;
    return kind === "text" ? TEXT : kind === "number" ? NUMBER : ["is"];
  }

  function defaultValue(field: FilterField): FilterConditionInput["value"] {
    const kind = FIELDS[field].kind;
    return kind === "flag" ? true : kind === "number" ? 0 : "";
  }

  function changeField(condition: FilterConditionInput, field: FilterField) {
    condition.field = field;
    condition.operator = operators(field)[0];
    condition.value = defaultValue(field);
  }

  function addCondition() {
    (group.conditions ??= []).push({ field: "genre", operator: "is", value: "" });
  }

  function addGroup() {
    (group.groups ??= []).push({ mode: "any", conditions: [], groups: [] });
  }
</script>

<fieldset class={["filter-group", { nested: depth > 0 }]}>
  <legend>{label}</legend>
  <div class="head">
    <label class="inline"
      >Match
      <select bind:value={group.mode} aria-label={`${label} match mode`}>
        <option value="all">all of</option>
        <option value="any">any of</option>
      </select>
    </label>
    {#if onremove}
      <button
        type="button"
        class="btn btn-ghost btn-sm"
        aria-label={`Remove ${label}`}
        onclick={onremove}><X size={14} /></button
      >
    {/if}
  </div>
  {#each group.conditions ?? [] as condition, index (index)}
    {@const meta = FIELDS[condition.field]}
    <div class="condition">
      <select
        aria-label={`${label} field ${index + 1}`}
        value={condition.field}
        onchange={(event) => changeField(condition, event.currentTarget.value as FilterField)}
      >
        {#each Object.entries(FIELDS) as [field, info] (field)}
          <option value={field}>{info.label}</option>
        {/each}
      </select>
      <select aria-label={`${label} operator ${index + 1}`} bind:value={condition.operator}>
        {#each operators(condition.field) as operator (operator)}
          <option value={operator}>{OPERATOR_LABELS[operator]}</option>
        {/each}
      </select>
      {#if meta.kind === "flag"}
        <select aria-label={`${label} value ${index + 1}`} bind:value={condition.value}>
          <option value={true}>yes</option>
          <option value={false}>no</option>
        </select>
      {:else if meta.kind === "number"}
        <input
          type="number"
          aria-label={`${label} value ${index + 1}`}
          value={condition.value}
          oninput={(event) => (condition.value = event.currentTarget.valueAsNumber || 0)}
        />
      {:else}
        <input aria-label={`${label} value ${index + 1}`} bind:value={condition.value} />
      {/if}
      <button
        type="button"
        class="btn btn-ghost btn-sm"
        aria-label={`Remove ${label} condition ${index + 1}`}
        onclick={() => group.conditions?.splice(index, 1)}><X size={14} /></button
      >
    </div>
  {/each}
  {#each group.groups ?? [] as sub, index (index)}
    <FilterGroupEditor
      group={sub}
      label={`${label} group ${index + 1}`}
      depth={depth + 1}
      onremove={() => group.groups?.splice(index, 1)}
    />
  {/each}
  <div class="actions">
    <button type="button" class="btn btn-ghost btn-sm" onclick={addCondition}
      ><Plus size={14} /> Condition</button
    >
    {#if depth < 2}
      <button type="button" class="btn btn-ghost btn-sm" onclick={addGroup}
        ><Plus size={14} /> Group</button
      >
    {/if}
  </div>
</fieldset>

<style>
  .filter-group {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-3);
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    min-width: 0;
  }
  .nested {
    background: var(--surface-2, transparent);
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
  .inline {
    display: inline-flex;
    align-items: center;
    gap: var(--space-2);
  }
  .condition {
    display: grid;
    grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr) minmax(0, 1.4fr) auto;
    gap: var(--space-2);
    align-items: center;
  }
  @media (max-width: 640px) {
    .condition {
      grid-template-columns: 1fr 1fr;
    }
  }
</style>

