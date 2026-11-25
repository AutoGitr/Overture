<script lang="ts">
  import FileUp from "@lucide/svelte/icons/file-up";
  import type { PresetListing } from "../../generated/rest/types.gen";
  import type { CollectionDraft, PresetItem } from "../utils/collectionDraft.svelte";
  import { errorMessage } from "../utils/errors";
  import type { SelectOption } from "../utils/selectOptions";
  import FieldRow from "./FieldRow.svelte";
  import Select from "./Select.svelte";

  let { draft }: { draft: CollectionDraft } = $props();

  const id = $props.id();

  /** Each set and collection of a listing, sets first, in the file's order. */
  function items(listing: PresetListing): PresetItem[] {
    const file = listing.file;
    if (!file) return [];
    return [
      ...file.groups
        .filter((group) => group.generator)
        .map((group) => ({ listing, kind: "set" as const, name: group.name })),
      ...file.collections.map((collection) => ({
        listing,
        kind: "collection" as const,
        name: collection.title,
      })),
    ];
  }

  /** The heading a listing's items sit under: its category, or the file it came from. */
  function heading(listing: PresetListing) {
    if (listing === draft.file) return "From file";
    const category = listing.preset?.category ?? "other";
    return category[0]?.toUpperCase() + category.slice(1);
  }

  /** The gallery comes ordered by category and title, a file read from disk first. */
  let choices = $derived(
    new Map(
      [...(draft.file ? [draft.file] : []), ...(draft.presets.data?.presets ?? [])]
        .flatMap(items)
        .map((item) => [`${item.listing.id}/${item.kind}/${item.name}`, item] as const),
    ),
  );
  let options = $derived<SelectOption[]>(
    [...choices].map(([value, item]) => ({
      value,
      label: item.name,
      // A preset of several says which each belongs to.
      detail: items(item.listing).length > 1 ? item.listing.preset?.title : undefined,
      group: heading(item.listing),
    })),
  );
  let chosen = $derived(
    [...choices].find(([, item]) => item === draft.preset)?.[0] ?? null,
  );
  let galleryError = $derived(
    draft.presets.error
      ? errorMessage(draft.presets.error, "Could not load OvertureDB's presets")
      : draft.presets.data?.error,
  );
</script>

<FieldRow
  label="Presets"
  for={`${id}-preset`}
  hint="Fills the form from an OvertureDB preset or an exported file; change anything before saving."
>
  <div class="preset-choice">
    <div class="preset-select">
      <Select
        id={`${id}-preset`}
        {options}
        placeholder={draft.presets.isFetching ? "Loading presets..." : "Start from a preset"}
        bind:value={
          () => chosen,
          (key) => {
            const item = key === null ? undefined : choices.get(key);
            if (item) draft.applyPreset(item);
          }
        }
      />
    </div>
    <label class="btn btn-secondary btn-sm load-file"
      ><FileUp size={14} />Load file
      <input
        class="sr-only"
        type="file"
        accept="application/json,.json"
        disabled={draft.fileRequest.isPending}
        onchange={(event) => {
          const file = event.currentTarget.files?.[0];
          if (file) void draft.loadFile(file);
          event.currentTarget.value = "";
        }}
      /></label
    >
  </div>
</FieldRow>
{#if galleryError}<p class="hint" role="status">{galleryError}</p>{/if}
{#if draft.preset}
  {@const preset = draft.preset.listing.preset}
  {#if preset}<p class="hint">{preset.title}: {preset.description}</p>{/if}
  {#each draft.preset.listing.setup as setup (setup)}
    <p class="hint" role="status">{setup}</p>
  {/each}
  {#if draft.presetGroup}
    <p class="hint">
      Saving gives the group "{draft.presetGroup.name}" the preset's defaults wherever it leaves
      one at Default.
    </p>
  {/if}
{/if}

<style>
  .preset-choice {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    align-items: center;
  }

  .preset-select {
    flex: 1 1 14rem;
    min-width: 0;
  }

  /* The input is hidden, so its label shows where focus is. */
  .load-file:focus-within {
    box-shadow: var(--focus-ring);
  }

  .hint {
    margin: 0;
  }
</style>
