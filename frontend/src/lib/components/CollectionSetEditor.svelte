<script lang="ts">
  import { createMutation } from "@tanstack/svelte-query";
  import { previewCollectionSetMutation } from "../../generated/rest/@tanstack/svelte-query.gen";
  import type { CollectionCapabilities, MediaType } from "../../generated/rest/types.gen";
  import type { SetGenerator } from "../utils/collectionForms.svelte";
  import { splitList } from "../utils/collectionCriteria";
  import { errorMessage } from "../utils/errors";
  import CriteriaEditor from "./CriteriaEditor.svelte";
  import PendingButton from "./PendingButton.svelte";

  let {
    generator,
    libraryId,
    mediaType,
    capabilities,
    group,
    minimum,
  }: {
    generator: SetGenerator;
    /** A new set's generator has no library until it saves, so the form passes its own. */
    libraryId: string;
    mediaType: MediaType;
    capabilities: CollectionCapabilities | undefined;
    /** The group the set saves into, whose collections the preview matches. */
    group: string;
    minimum: number | null;
  } = $props();

  const id = $props.id();
  const preview = createMutation(() => previewCollectionSetMutation());
  let dimensions = $derived(capabilities?.dimensions ?? []);
  // Overture counts the values itself; Plex then evaluates smart collections.
  let fields = $derived(
    (capabilities?.fields ?? []).filter(
      (field) => field.local && (!generator.smart || field.smart),
    ),
  );
  let entries = $derived(
    preview.data && preview.variables?.body.generator.library_id === libraryId
      ? preview.data
      : null,
  );
  let created = $derived(entries?.filter((entry) => !entry.below_minimum) ?? []);

  function runPreview() {
    preview.mutate({
      body: {
        media_type: mediaType,
        generator: { ...$state.snapshot(generator), library_id: libraryId },
        group: group.trim() || null,
        minimum_items: minimum,
      },
    });
  }
</script>

<label class="form-label">
  One collection per
  <select
    value={generator.dimension}
    onchange={(event) => {
      const dimension = dimensions.find((entry) => entry.dimension === event.currentTarget.value);
      if (!dimension) return;
      generator.dimension = dimension.dimension;
      generator.title_format = dimension.title_format;
    }}
  >
    {#if !dimensions.some((entry) => entry.dimension === generator.dimension)}
      <option value={generator.dimension} disabled>Unavailable here</option>
    {/if}
    {#each dimensions as entry (entry.dimension)}
      <option value={entry.dimension}>{entry.label}</option>
    {/each}
  </select>
</label>
<label class="form-label">
  Title
  <input required maxlength="200" bind:value={generator.title_format} placeholder={"{value}"} />
  <span class="hint">&#123;value&#125; becomes each value, such as 1990 or Action.</span>
</label>
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
  <div class="affixes">
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
{#if capabilities?.smart}
  <label class="form-row">
    <input type="checkbox" bind:checked={generator.smart} />
    Create Plex smart collections
  </label>
{/if}
<label class="form-row">
  <input type="checkbox" bind:checked={generator.enabled} />
  Add and update collections on schedule
</label>
<div class="form-wide">
  <CriteriaEditor
    group={generator.criteria}
    {fields}
    sources={capabilities?.sources ?? []}
    {mediaType}
    {libraryId}
    label="Only titles matching"
  />
  <span class="hint">Every collection in the set also requires these conditions.</span>
</div>
<div class="form-wide preview">
  <PendingButton
    type="button"
    class="btn btn-secondary"
    pending={preview.isPending}
    pendingLabel="Previewing..."
    disabled={!libraryId}
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
      {#each entries as entry (entry.value)}
        <li class={{ skipped: entry.below_minimum }}>
          <span>{entry.title}</span>
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
  .affixes {
    display: flex;
    gap: var(--space-2);
    @media (max-width: 640px) {
      flex-direction: column;
    }
  }

  .affixes input {
    flex: 1;
    min-width: 0;
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
