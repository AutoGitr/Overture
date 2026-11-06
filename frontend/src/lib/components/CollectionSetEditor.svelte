<script lang="ts">
  import { countOf } from "../utils/plural";
  import { createMutation } from "@tanstack/svelte-query";
  import { previewCollectionSetMutation } from "../../generated/rest/@tanstack/svelte-query.gen";
  import type {
    CollectionCapabilities,
    LibrarySectionRead,
  } from "../../generated/rest/types.gen";
  import { withDimension, type SetGenerator } from "../utils/collectionForms.svelte";
  import { emptyGroup, splitList } from "../utils/collectionCriteria";
  import { errorMessage } from "../utils/errors";
  import CriteriaEditor from "./CriteriaEditor.svelte";
  import FieldRow from "./FieldRow.svelte";
  import PendingButton from "./PendingButton.svelte";
  import SegmentedControl from "./SegmentedControl.svelte";
  import SetDimensionField from "./SetDimensionField.svelte";

  let {
    generator = $bindable(),
    libraryIds,
    libraries,
    capabilities,
    group,
    minimum,
    standalone = false,
  }: {
    generator: SetGenerator;
    /** The libraries the set creates its collections in. */
    libraryIds: string[];
    libraries: LibrarySectionRead[];
    capabilities: CollectionCapabilities | undefined;
    /** The group the set saves into, whose collections the preview matches. */
    group: string;
    minimum: number | null;
    /** Edit the dimension and title template here, where no Setup section holds them. */
    standalone?: boolean;
  } = $props();

  const id = $props.id();
  const EVALUATION = [
    ["overture", "Overture"],
    ["smart", "Plex (smart)"],
  ] as const;
  const preview = createMutation(() => previewCollectionSetMutation());
  let dimensions = $derived(capabilities?.dimensions ?? []);
  let dimension = $derived(dimensions.find((entry) => entry.dimension === generator.dimension));
  let custom = $derived(generator.dimension === "custom");
  let libraryId = $derived(libraryIds[0] ?? "");
  /** Criteria suggest values from the first library; only shared fields are on offer. */
  let mediaType = $derived(
    libraries.find((library) => library.id === libraryId)?.media_type ?? "movie",
  );
  // Overture counts values itself, then Plex may evaluate smart collections. Plex
  // counts the values only it knows, so it must test the shared criteria itself.
  let fields = $derived(
    (capabilities?.fields ?? []).filter((field) =>
      dimension?.smart_only
        ? field.smart && !field.labelled
        : field.local && (!generator.smart || field.smart),
    ),
  );
  let sharedSources = $derived(dimension?.smart_only ? [] : (capabilities?.sources ?? []));
  let entries = $derived(preview.data ?? null);
  let created = $derived(entries?.filter((entry) => !entry.below_minimum) ?? []);

  function runPreview() {
    preview.mutate({
      body: {
        generator: { ...$state.snapshot(generator), library_ids: libraryIds },
        group: group.trim() || null,
        minimum_items: minimum,
      },
    });
  }

  function libraryName(id: string) {
    return libraries.find((library) => library.id === id)?.title ?? id;
  }
</script>

{#if standalone}
  <SetDimensionField
    value={generator.dimension}
    {dimensions}
    onchoose={(chosen) => Object.assign(generator, withDimension(generator, chosen, dimension))}
  />
  <FieldRow
    label="Title template"
    for={`${id}-title`}
    hint={"{value} becomes each value, such as 1990 or Action."}
  >
    <input
      id={`${id}-title`}
      required
      maxlength="200"
      bind:value={generator.title_format}
      placeholder={"{value}"}
    />
  </FieldRow>
{/if}

{#if !custom}
  <FieldRow
    label="Most common only"
    for={`${id}-top`}
    hint="Keep the values with the most titles, such as the top 25 directors."
  >
    <input
      id={`${id}-top`}
      type="number"
      min="1"
      max="500"
      placeholder="Every value"
      value={generator.top ?? ""}
      oninput={(event) =>
        (generator.top = event.currentTarget.value ? event.currentTarget.valueAsNumber : null)}
    />
  </FieldRow>
  <FieldRow
    label="Only these values"
    for={`${id}-include`}
    hint="Values or titles, separated by commas."
  >
    <input
      id={`${id}-include`}
      placeholder="All values"
      value={(generator.include ?? []).join(", ")}
      onchange={(event) => (generator.include = splitList(event.currentTarget.value))}
    />
  </FieldRow>
  <FieldRow label="Skip these values" for={`${id}-exclude`}>
    <input
      id={`${id}-exclude`}
      placeholder="None"
      value={(generator.exclude ?? []).join(", ")}
      onchange={(event) => (generator.exclude = splitList(event.currentTarget.value))}
    />
  </FieldRow>
  <FieldRow
    label="Remove from names"
    for={`${id}-prefix`}
    hint="For example, The Matrix Collection becomes Matrix."
  >
    <input
      id={`${id}-prefix`}
      maxlength="100"
      placeholder="Leading text, e.g. The"
      bind:value={generator.strip_prefix}
    />
    <input
      aria-label="Trailing text to remove"
      maxlength="100"
      placeholder="Trailing text, e.g. Collection"
      bind:value={generator.strip_suffix}
    />
  </FieldRow>
{/if}

{#if capabilities?.smart && !dimension?.smart_only}
  <FieldRow
    label="Evaluated by"
    hint={generator.smart
      ? "Plex keeps each collection current. Conditions Plex cannot test, such as lists and TMDB facts, use labels Overture refreshes on each sync."
      : undefined}
  >
    <SegmentedControl
      label="Evaluated by"
      options={EVALUATION}
      bind:value={() => (generator.smart ? "smart" : "overture"), (value) => (generator.smart = value === "smart")}
    />
  </FieldRow>
{/if}

{#if custom}
  <div class="custom-values">
    <span class="form-label">Collections</span>
    {#each generator.custom_values ?? [] as value, index (index)}
      <fieldset class="custom-value">
        <legend class="sr-only">Collection {index + 1}</legend>
        <div class="custom-head">
          <input
            aria-label={`Collection ${index + 1} name`}
            maxlength="200"
            placeholder="Name, such as A"
            bind:value={value.name}
          />
          <button
            type="button"
            class="btn btn-ghost btn-sm"
            onclick={() =>
              (generator.custom_values = (generator.custom_values ?? []).filter(
                (_, other) => other !== index,
              ))}>Remove</button
          >
        </div>
        <CriteriaEditor
          bind:group={value.criteria}
          {fields}
          sources={capabilities?.sources ?? []}
          {mediaType}
          {libraryId}
          label={`Collection ${index + 1} criteria`}
        />
      </fieldset>
    {/each}
    <button
      type="button"
      class="btn btn-secondary btn-sm"
      onclick={() =>
        (generator.custom_values = [
          ...(generator.custom_values ?? []),
          { name: "", criteria: emptyGroup() },
        ])}>Add collection</button
    >
  </div>
{:else}
  <div class="aliases">
    <span class="form-label">Rename or merge values</span>
    {#each generator.aliases ?? [] as alias, index (index)}
      <div class="pair">
        <input
          aria-label={`Alias ${index + 1} values`}
          placeholder="Values, such as Sci-Fi, Science Fiction"
          value={alias.values.join(", ")}
          onchange={(event) => (alias.values = splitList(event.currentTarget.value))}
        />
        <input
          aria-label={`Alias ${index + 1} title`}
          maxlength="200"
          placeholder="Collection title"
          bind:value={alias.name}
        />
        <button
          type="button"
          class="btn btn-ghost btn-sm"
          onclick={() =>
            (generator.aliases = (generator.aliases ?? []).filter((_, other) => other !== index))}
          >Remove</button
        >
      </div>
    {/each}
    <button
      type="button"
      class="btn btn-secondary btn-sm"
      onclick={() => (generator.aliases = [...(generator.aliases ?? []), { values: [], name: "" }])}
      >Add alias</button
    >
    <span class="hint">One value renames its collection; several make one collection.</span>
  </div>
{/if}
<div>
  <CriteriaEditor
    bind:group={generator.criteria}
    {fields}
    sources={sharedSources}
    {mediaType}
    {libraryId}
    label="Every collection also needs"
  />
</div>
<div class="preview">
  <div class="actions-row">
    <PendingButton
      type="button"
      class="btn btn-secondary"
      pending={preview.isPending}
      pendingLabel="Previewing..."
      disabled={!libraryIds.length}
      onclick={runPreview}>Preview collections</PendingButton
    >
  </div>
  {#if preview.error}
    <p role="alert">{errorMessage(preview.error, "Could not preview the set")}</p>
  {:else if entries}
    <p class="hint">
      {countOf(created.length, "collection")}, {entries.length - created.length}
      below the minimum.
    </p>
    <ul class="entries">
      {#each entries as entry (`${entry.library_id}:${entry.value}`)}
        <li class={{ skipped: entry.below_minimum }}>
          <span
            >{entry.title}{libraryIds.length > 1 ? ` (${libraryName(entry.library_id)})` : ""}</span
          >
          <span class="hint"
            >{countOf(entry.member_count, "title")}{entry.below_minimum
              ? ", below minimum"
              : entry.collection_id
                ? ", exists"
                : ", new"}</span
          >
        </li>
      {/each}
    </ul>
  {/if}
</div>

<style>
  .pair,
  .custom-head {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
  }

  .pair input,
  .custom-head input {
    flex: 1 1 8rem;
    min-width: 0;
  }

  .custom-values,
  .aliases {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: var(--space-2);
  }

  .custom-value {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    width: 100%;
    min-width: 0;
    margin: 0;
    padding: var(--space-3);
    border: var(--border-subtle);
    border-radius: var(--radius-md);
  }

  .aliases .pair {
    width: 100%;
  }

  .preview {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: var(--space-2);
  }

  .entries {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(100%, 220px), 1fr));
    gap: var(--space-1) var(--space-4);
    width: 100%;
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .entries li {
    display: flex;
    justify-content: space-between;
    gap: var(--space-2);
    font-size: var(--text-sm);
  }

  .skipped {
    opacity: 0.55;
  }
</style>
