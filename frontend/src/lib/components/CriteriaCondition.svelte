<script lang="ts">
  import Copy from "@lucide/svelte/icons/copy";
  import CopyPlus from "@lucide/svelte/icons/copy-plus";
  import X from "@lucide/svelte/icons/x";
  import { createQuery } from "@tanstack/svelte-query";
  import { listCollectionFieldValuesOptions } from "../../generated/rest/@tanstack/svelte-query.gen";
  import type {
    CollectionFieldRead,
    CollectionSourceRead,
    ConditionInput,
    MediaType,
  } from "../../generated/rest/types.gen";
  import {
    OPERATOR_LABELS,
    SOURCE_OPERATOR_LABELS,
    defaultValue,
    fieldCondition,
    sourceCondition,
  } from "../utils/collectionCriteria";
  import { countOf } from "../utils/plural";
  import SourceFields from "./SourceFields.svelte";
  import DataStatus from "./DataStatus.svelte";

  let {
    condition = $bindable(),
    fields,
    sources,
    mediaType,
    libraryId,
    label,
    onchange,
    onduplicate,
    oncopy,
    onremove,
  }: {
    condition: ConditionInput;
    fields: CollectionFieldRead[];
    sources: CollectionSourceRead[];
    mediaType: MediaType;
    libraryId: string;
    /** Names the condition for assistive technology, such as "Criteria condition 2". */
    label: string;
    /** Replaces the condition when another field or source is chosen. */
    onchange: (condition: ConditionInput) => void;
    /** Adds a copy of the condition right after it. */
    onduplicate: () => void;
    /** Keeps the condition to paste into these or other criteria. */
    oncopy: () => void;
    onremove: () => void;
  } = $props();

  const listId = $props.id();
  let field = $derived(
    condition.kind === "field"
      ? fields.find((entry) => entry.field === condition.field)
      : undefined,
  );
  let subject = $derived(
    condition.kind === "field" ? `field:${condition.field}` : `source:${condition.source.type}`,
  );
  // Tag and text values are suggested from the library, or from Plex for fields
  // only Plex knows.
  let suggested = $derived(field?.kind === "tag" || field?.kind === "text");
  let typed = $derived(condition.kind === "field" ? String(condition.value).trim() : "");
  // TMDB knows keywords no title has yet, so a keyword condition asks it about
  // what is typed, once typing pauses.
  let searchesTmdb = $derived(condition.kind === "field" && condition.field === "tmdb_keyword");
  let asked = $state("");
  $effect(() => {
    const query = searchesTmdb ? typed : "";
    const timer = setTimeout(() => (asked = query), 300);
    return () => clearTimeout(timer);
  });
  const values = createQuery(() => ({
    ...listCollectionFieldValuesOptions({
      query: {
        media_type: mediaType,
        library_id: libraryId,
        field: condition.kind === "field" ? condition.field : "title",
        ...(searchesTmdb && asked ? { query: asked } : {}),
      },
    }),
    enabled: suggested && !!libraryId,
    placeholderData: (previous) => previous,
  }));

  /** Suggestions shown at once; a library can hold thousands of values. */
  const MAX_SUGGESTIONS = 50;
  // Any value can be typed, such as a TMDB keyword no title has yet; the
  // library's values are suggestions filtered to what is typed to keep the list short.
  let suggestions = $derived.by(() => {
    const lower = typed.toLocaleLowerCase();
    const matching = lower
      ? (values.data ?? []).filter((entry) => entry.value.toLocaleLowerCase().includes(lower))
      : (values.data ?? []);
    return matching.slice(0, MAX_SUGGESTIONS);
  });

  function choose(value: string) {
    const [kind, name] = value.split(":");
    const chosenField = fields.find((entry) => entry.field === name);
    const chosenSource = sources.find((entry) => entry.type === name);
    if (kind === "field" && chosenField) onchange(fieldCondition(chosenField));
    else if (kind === "source" && chosenSource) onchange(sourceCondition(chosenSource.type));
  }
</script>

<div class="condition" role="group" aria-label={label}>
  <select
    aria-label={`${label} field`}
    value={subject}
    onchange={(e) => choose(e.currentTarget.value)}
  >
    {#if condition.kind === "field" && !field}
      <option value={subject} disabled>Unavailable field</option>
    {/if}
    <optgroup label="Metadata">
      {#each fields as entry (entry.field)}
        <option value={`field:${entry.field}`}>{entry.label}</option>
      {/each}
    </optgroup>
    <optgroup label="Lists & tags">
      {#each sources as entry (entry.type)}
        <option value={`source:${entry.type}`} disabled={!!entry.unavailable}
          >{entry.label}{entry.unavailable ? ` (${entry.unavailable})` : ""}</option
        >
      {/each}
    </optgroup>
  </select>

  {#if condition.kind === "source"}
    <select aria-label={`${label} operator`} bind:value={condition.operator}>
      {#each Object.entries(SOURCE_OPERATOR_LABELS) as [operator, operatorLabel] (operator)}
        <option value={operator}>{operatorLabel}</option>
      {/each}
    </select>
    <SourceFields bind:source={condition.source} {mediaType} {label} />
  {:else if field}
    {@const kind = field.kind}
    <select
      aria-label={`${label} operator`}
      value={condition.operator}
      onchange={(event) => {
        const operator = field.operators.find((entry) => entry === event.currentTarget.value);
        if (!operator || condition.kind !== "field") return;
        const dateShape = (op: string) => op === "before" || op === "after";
        if (dateShape(operator) !== dateShape(condition.operator ?? "is"))
          condition.value = defaultValue(field, operator);
        condition.operator = operator;
      }}
    >
      {#each field.operators as operator (operator)}
        <option value={operator}>{OPERATOR_LABELS[operator]}</option>
      {/each}
    </select>
    {#if kind === "boolean"}
      <select
        aria-label={`${label} value`}
        value={String(condition.value)}
        onchange={(event) => (condition.value = event.currentTarget.value === "true")}
      >
        <option value="true">true</option>
        <option value="false">false</option>
      </select>
    {:else if condition.operator === "before" || condition.operator === "after"}
      <input
        type="date"
        required
        aria-label={`${label} value`}
        value={String(condition.value)}
        oninput={(event) => (condition.value = event.currentTarget.value)}
      />
    {:else if kind === "number" || kind === "date"}
      <input
        type="number"
        required
        step="any"
        aria-label={`${label} value`}
        value={condition.value}
        oninput={(event) => (condition.value = event.currentTarget.valueAsNumber || 0)}
      />
    {:else}
      <input
        required
        aria-label={`${label} value`}
        list={suggested ? listId : undefined}
        value={String(condition.value)}
        oninput={(event) => (condition.value = event.currentTarget.value)}
      />
      {#if suggested}
        <datalist id={listId}>
          {#each suggestions as entry (entry.value)}
            <option value={entry.value}
              >{entry.count
                ? countOf(entry.count, "title")
                : searchesTmdb
                  ? "On TMDB, no title yet"
                  : ""}</option
            >
          {/each}
        </datalist>
      {/if}
    {/if}
  {:else}
    <span class="hint">The media server cannot test this field here; choose another.</span>
  {/if}

  <div class="row-actions">
    <button
      type="button"
      class="btn btn-ghost btn-sm btn-icon"
      aria-label={`Copy ${label}`}
      title="Copy condition, to paste into any criteria"
      onclick={oncopy}><Copy size={14} /></button
    >
    <button
      type="button"
      class="btn btn-ghost btn-sm btn-icon"
      aria-label={`Duplicate ${label}`}
      title="Duplicate condition"
      onclick={onduplicate}><CopyPlus size={14} /></button
    >
    <button
      type="button"
      class="btn btn-ghost btn-sm btn-icon"
      aria-label={`Remove ${label}`}
      title="Remove condition"
      onclick={onremove}><X size={14} /></button
    >
  </div>
  {#if suggested && values.error}
    <div class="value-status">
      <DataStatus
        label="available values"
        error={values.error}
        loading={values.isFetching}
        hasData={values.data !== undefined}
        onretry={() => values.refetch()}
      />
    </div>
  {/if}
</div>

<style>
  /* Field, operator, value and actions share one row; on a phone the field,
     the longest of them, takes a row of its own, the operator sits beside the
     actions and the value gets the whole row under them. */
  .condition {
    display: grid;
    grid-template-columns: minmax(0, 1.2fr) minmax(0, 1fr) minmax(0, 1.6fr) auto;
    gap: var(--space-2);
    align-items: start;
    @media (max-width: 640px) {
      grid-template-columns: minmax(0, 1fr) auto;
    }
  }

  .condition > select:first-child {
    @media (max-width: 640px) {
      grid-column: 1 / -1;
    }
  }

  .value-status {
    grid-column: 1 / -1;
  }

  .row-actions {
    display: flex;
    gap: 2px;
    @media (max-width: 640px) {
      grid-row: 2;
      grid-column: 2;
    }
  }

  .condition > :global(.source-fields),
  .condition > .hint,
  .condition > input,
  .condition > select:nth-of-type(3) {
    @media (max-width: 640px) {
      grid-column: 1 / -1;
      grid-row: 3;
    }
  }
</style>
