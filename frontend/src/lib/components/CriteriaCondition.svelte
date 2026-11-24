<script lang="ts">
  import Copy from "@lucide/svelte/icons/copy";
  import CopyPlus from "@lucide/svelte/icons/copy-plus";
  import X from "@lucide/svelte/icons/x";
  import { createQuery } from "@tanstack/svelte-query";
  import { listCollectionFieldValuesOptions } from "../../generated/rest/@tanstack/svelte-query.gen";
  import type {
    CollectionFieldRead,
    CollectionSourceRead,
    ConditionOutput,
    FilterOperator,
    MediaType,
  } from "../../generated/rest/types.gen";
  import {
    defaultValue,
    fieldCondition,
    isDateOperator,
    sourceCondition,
  } from "../utils/collectionCriteria";
  import { FIELD_LABELS, OPERATOR_LABELS, SOURCE_OPERATOR_LABELS } from "../../generated/settings";
  import { countOf } from "../utils/plural";
  import SourceFields from "./SourceFields.svelte";
  import DataStatus from "./DataStatus.svelte";
  import Select from "./Select.svelte";
  import { fromLabels, type SelectOption } from "../utils/selectOptions";
  import ValueCombobox from "./ValueCombobox.svelte";

  let {
    condition = $bindable(),
    fields,
    sources,
    mediaType,
    libraryId,
    scope,
    label,
    onchange,
    onduplicate,
    oncopy,
    onremove,
  }: {
    condition: ConditionOutput;
    fields: CollectionFieldRead[];
    sources: CollectionSourceRead[];
    mediaType: MediaType;
    /** The library whose values are suggested; null for every library of the media type. */
    libraryId: string | null;
    /** What the criteria test, as a message names it, such as "Movies on Plex". */
    scope: string;
    /** Names the condition for assistive technology, such as "Criteria condition 2". */
    label: string;
    /** Replaces the condition when another field or source is chosen. */
    onchange: (condition: ConditionOutput) => void;
    /** Adds a copy of the condition right after it. */
    onduplicate: () => void;
    /** Keeps the condition to paste into these or other criteria. */
    oncopy: () => void;
    onremove: () => void;
  } = $props();

  let field = $derived(
    condition.kind === "field"
      ? fields.find((entry) => entry.field === condition.field)
      : undefined,
  );
  let subject = $derived(
    condition.kind === "field" ? `field:${condition.field}` : `source:${condition.source.type}`,
  );
  /** A field holding a fixed set of values offers just those. */
  let fixed = $derived(field?.choices ?? []);
  /** A tag or text field suggests the values the libraries hold, as it is typed. */
  let suggested = $derived((field?.kind === "tag" || field?.kind === "text") && !fixed.length);
  let current = $derived(condition.kind === "field" ? String(condition.value) : "");
  // TMDB knows keywords no title has yet, so a keyword condition asks it about
  // what is typed, once typing pauses.
  let searchesTmdb = $derived(condition.kind === "field" && condition.field === "tmdb_keyword");
  let asked = $state("");
  $effect(() => {
    const query = searchesTmdb ? current.trim() : "";
    const timer = setTimeout(() => (asked = query), 300);
    return () => clearTimeout(timer);
  });
  const values = createQuery(() => ({
    ...listCollectionFieldValuesOptions({
      query: {
        media_type: mediaType,
        // Without a library, the values every library of the media type holds.
        ...(libraryId ? { library_id: libraryId } : {}),
        field: condition.kind === "field" ? condition.field : "title",
        ...(searchesTmdb && asked ? { query: asked } : {}),
      },
    }),
    enabled: suggested,
    placeholderData: (previous) => previous,
  }));
  /** The fixed value the condition holds, as its field's criteria match it. */
  let chosenFixed = $derived.by(() => {
    const exact = fixed.find((entry) => entry.value === current);
    if (exact || !field?.ignores_case) return exact;
    const folded = current.toLocaleLowerCase();
    return fixed.find((entry) => entry.value.toLocaleLowerCase() === folded);
  });
  /** The condition's field as people know it, whether or not these criteria offer it. */
  let fieldName = $derived(condition.kind === "field" ? FIELD_LABELS[condition.field] : "");
  /** Names an ID the condition holds that no listed value names. */
  let unlisted = $derived.by(() => {
    if (!current) return "";
    // An ID is named by the list, which may still be on its way.
    return values.isLoading ? "Loading…" : `${fieldName} #${current} (holds no title)`;
  });

  function choose(value: string) {
    const [kind, name] = value.split(":");
    const chosenField = fields.find((entry) => entry.field === name);
    const chosenSource = sources.find((entry) => entry.type === name);
    if (kind === "field" && chosenField) onchange(fieldCondition(chosenField));
    else if (kind === "source" && chosenSource) onchange(sourceCondition(chosenSource.type));
  }

  /** A date value and a relative or plain one do not convert, so switching resets it. */
  function setOperator(chosen: CollectionFieldRead, operator: FilterOperator) {
    if (condition.kind !== "field") return;
    if (isDateOperator(operator) !== isDateOperator(condition.operator))
      condition.value = defaultValue(chosen, operator);
    condition.operator = operator;
  }

  let subjectOptions = $derived<SelectOption[]>([
    ...fields.map((entry) => ({
      value: `field:${entry.field}`,
      label: entry.label,
      group: "Metadata",
    })),
    ...sources.map((entry) => ({
      value: `source:${entry.type}`,
      label: entry.unavailable ? `${entry.label} (${entry.unavailable})` : entry.label,
      disabled: !!entry.unavailable,
      group: "Lists & tags",
    })),
  ]);
  let operatorOptions = $derived(
    (field?.operators ?? []).map((operator) => ({
      value: operator,
      label: OPERATOR_LABELS[operator],
    })),
  );
  const SOURCE_OPERATORS = fromLabels(SOURCE_OPERATOR_LABELS);
  const BOOLEAN_OPTIONS = [
    { value: true, label: "true" },
    { value: false, label: "false" },
  ];
</script>

<div class="condition" role="group" aria-label={label}>
  <Select
    label={`${label} field`}
    options={subjectOptions}
    placeholder={fieldName && !field ? `${fieldName} (unavailable)` : ""}
    bind:value={() => subject, choose}
  />

  {#if condition.kind === "source"}
    <Select
      label={`${label} operator`}
      options={SOURCE_OPERATORS}
      bind:value={condition.operator}
    />
    <SourceFields bind:source={condition.source} {mediaType} {label} />
  {:else if field}
    {@const kind = field.kind}
    <Select
      label={`${label} operator`}
      options={operatorOptions}
      bind:value={() => condition.operator, (operator) => setOperator(field, operator)}
    />
    {#if kind === "boolean"}
      <!-- Only `true` is true: a value read back as text must not show as set. -->
      <Select
        label={`${label} value`}
        options={BOOLEAN_OPTIONS}
        bind:value={() => condition.value === true, (next) => (condition.value = next)}
      />
    {:else if isDateOperator(condition.operator)}
      <input
        type="date"
        required
        aria-label={`${label} value`}
        value={String(condition.value)}
        oninput={(event) => (condition.value = event.currentTarget.value)}
      />
    {:else if fixed.length}
      <Select
        label={`${label} value`}
        options={fixed}
        placeholder={current ? `${current} (not one of its values)` : "Choose a value"}
        bind:value={() => chosenFixed?.value ?? current, (next) => (condition.value = next)}
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
      <ValueCombobox
        bind:value={() => current, (typed) => (condition.value = typed)}
        options={values.data ?? []}
        strict={field.by_id}
        label={`${label} value`}
        {unlisted}
        describe={(entry) =>
          entry.count ? countOf(entry.count, "title") : searchesTmdb ? "On TMDB, no title yet" : ""}
      />
    {/if}
  {:else}
    <span class="hint">{fieldName} cannot be tested for {scope}; choose another field.</span>
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

  .condition > :global(.combobox:first-child) {
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
  .condition > :global(.combobox:nth-child(3)),
  .condition > .hint,
  .condition > input {
    @media (max-width: 640px) {
      grid-column: 1 / -1;
      grid-row: 3;
    }
  }
</style>
