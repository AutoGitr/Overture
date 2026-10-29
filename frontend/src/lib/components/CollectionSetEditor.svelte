<script lang="ts">
  import { createMutation } from "@tanstack/svelte-query";
  import { previewCollectionSetMutation } from "../../generated/rest/@tanstack/svelte-query.gen";
  import type {
    CollectionCapabilities,
    LibrarySectionRead,
    MediaType,
  } from "../../generated/rest/types.gen";
  import type { SetGenerator } from "../utils/collectionForms.svelte";
  import { emptyGroup, splitList } from "../utils/collectionCriteria";
  import { errorMessage } from "../utils/errors";
  import CriteriaEditor from "./CriteriaEditor.svelte";
  import PendingButton from "./PendingButton.svelte";
  import SegmentedControl from "./SegmentedControl.svelte";

  let {
    generator,
    libraryIds,
    libraries,
    mediaType,
    capabilities,
    group,
    minimum,
    titled = false,
  }: {
    generator: SetGenerator;
    /** The libraries the set creates its collections in. */
    libraryIds: string[];
    libraries: LibrarySectionRead[];
    mediaType: MediaType;
    capabilities: CollectionCapabilities | undefined;
    /** The group the set saves into, whose collections the preview matches. */
    group: string;
    minimum: number | null;
    /** Edit the title template here, where no Setup section holds it. */
    titled?: boolean;
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
  // Overture counts values itself; Plex then evaluates smart collections.
  let fields = $derived(
    (capabilities?.fields ?? []).filter(
      (field) => (dimension?.smart_only || field.local) && (!generator.smart || field.smart),
    ),
  );
  let entries = $derived(preview.data ?? null);
  let created = $derived(entries?.filter((entry) => !entry.below_minimum) ?? []);

  function runPreview() {
    preview.mutate({
      body: {
        media_type: mediaType,
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

<label class="form-label">
  Split by
  <select
    value={generator.dimension}
    onchange={(event) => {
      const chosen = dimensions.find((entry) => entry.dimension === event.currentTarget.value);
      if (!chosen) return;
      generator.dimension = chosen.dimension;
      generator.title_format = chosen.title_format;
      if (chosen.smart_only) generator.smart = true;
      if (chosen.dimension === "custom" && !generator.custom_values?.length)
        generator.custom_values = [{ name: "", criteria: emptyGroup() }];
      if (chosen.dimension !== "custom") generator.custom_values = [];
    }}
  >
    {#if !dimension}
      <option value={generator.dimension} disabled>Unavailable here</option>
    {/if}
    {#each dimensions as entry (entry.dimension)}
      <option value={entry.dimension}>{entry.label}{entry.smart_only ? " (Plex smart)" : ""}</option
      >
    {/each}
  </select>
  {#if dimension?.smart_only}<span class="hint">Only Plex knows these values.</span>{/if}
</label>
{#if titled}
  <label class="form-label">
    Title template
    <input required maxlength="200" bind:value={generator.title_format} placeholder={"{value}"} />
    <span class="hint">&#123;value&#125; becomes each value, such as 1990 or Action.</span>
  </label>
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
          group={value.criteria}
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
  <label class="form-label">
    Most common only
    <input
      type="number"
      min="1"
      max="500"
      placeholder="Every value"
      value={generator.top ?? ""}
      oninput={(event) =>
        (generator.top = event.currentTarget.value ? event.currentTarget.valueAsNumber : null)}
    />
    <span class="hint">Keep the values with the most titles, such as the top 25 directors.</span>
  </label>
  <label class="form-label">
    Only these values
    <input
      placeholder="All values"
      value={(generator.include ?? []).join(", ")}
      onchange={(event) => (generator.include = splitList(event.currentTarget.value))}
    />
    <span class="hint">Values or titles, separated by commas.</span>
  </label>
  <label class="form-label">
    Skip these values
    <input
      placeholder="None"
      value={(generator.exclude ?? []).join(", ")}
      onchange={(event) => (generator.exclude = splitList(event.currentTarget.value))}
    />
  </label>
  <div class="form-label">
    <label for={`${id}-prefix`}>Remove from names</label>
    <div class="pair">
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
    </div>
    <span class="hint">For example, The Matrix Collection becomes Matrix.</span>
  </div>
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

{#if capabilities?.smart}
  <div class="form-label">
    <span>Evaluated by</span>
    <SegmentedControl
      --segmented-margin="0"
      label="Evaluated by"
      options={EVALUATION}
      bind:value={
        () => (generator.smart ? "smart" : "overture"),
        (value) => (generator.smart = value === "smart" || !!dimension?.smart_only)
      }
    />
  </div>
{/if}
<div>
  <CriteriaEditor
    group={generator.criteria}
    {fields}
    sources={capabilities?.sources ?? []}
    {mediaType}
    {libraryId}
    label="Every collection also needs"
  />
</div>
<div class="preview">
  <PendingButton
    type="button"
    class="btn btn-secondary"
    pending={preview.isPending}
    pendingLabel="Previewing..."
    disabled={!libraryIds.length}
    onclick={runPreview}>Preview collections</PendingButton
  >
  {#if preview.error}
    <p role="alert">{errorMessage(preview.error, "Could not preview the set")}</p>
  {:else if entries}
    <p class="hint">
      {created.length} collection{created.length === 1 ? "" : "s"}, {entries.length -
        created.length}
      below the minimum.
    </p>
    <ul class="entries">
      {#each entries as entry (`${entry.library_id}:${entry.value}`)}
        <li class={{ skipped: entry.below_minimum }}>
          <span
            >{entry.title}{libraryIds.length > 1 ? ` (${libraryName(entry.library_id)})` : ""}</span
          >
          <span class="hint"
            >{entry.member_count}
            {entry.member_count === 1 ? "title" : "titles"}{entry.below_minimum
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
    gap: var(--space-2);
    @media (max-width: 640px) {
      flex-direction: column;
    }
  }

  .pair input,
  .custom-head input {
    flex: 1;
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
