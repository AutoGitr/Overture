<script lang="ts">
  import { createQuery } from "@tanstack/svelte-query";
  import { getLibrariesOptions } from "../../generated/rest/@tanstack/svelte-query.gen";
  import { CollectionCreation } from "../utils/collectionForms.svelte";
  import { uiState } from "../stores/uiState.svelte";
  import DataStatus from "./DataStatus.svelte";
  import PopupShell from "./PopupShell.svelte";
  const form = new CollectionCreation(uiState.sidebarTab);
  const libraries = createQuery(() =>
    getLibrariesOptions({ query: { media_type: form.mediaType } }),
  );
</script>

<PopupShell title="Generate collections" onclose={() => uiState.closePopup()}>
  <p class="text-muted">
    Build dynamic collections from your library. Review the preview and select the collections to
    create.
  </p>
  <DataStatus
    label="libraries"
    error={libraries.error}
    loading={libraries.isFetching}
    hasData={libraries.data !== undefined}
    onretry={() => libraries.refetch()}
  />
  <fieldset class="options-col" disabled={form.generateRequest.isPending || form.preview.isPending}>
    <legend>Collection presets</legend>
    <label class="form-label"
      >Library<select bind:value={form.libraryId} onchange={() => form.resetPreview()}
        ><option value="">Select a library</option
        >{#each libraries.data ?? [] as library (library.id)}<option value={library.id}
            >{library.title}</option
          >{/each}</select
      ></label
    >
    <label class="form-label"
      >Group by<select bind:value={form.preset} onchange={() => form.resetPreview()}
        ><option value="decades">Decades</option><option value="genres">Genres</option><option
          value="studios">Studios</option
        ></select
      ></label
    >
    <button class="btn" disabled={!form.libraryId} onclick={() => void form.previewCollections()}
      >Preview collections</button
    >
    {#if form.preview.data}
      {#each form.preview.data as preset (preset.title)}<label class="form-row"
          ><input
            type="checkbox"
            checked={form.titles.has(preset.title)}
            onchange={() => form.toggleTitle(preset.title)}
          />{preset.title} ({preset.count} members)</label
        >{/each}
      {#if !form.preview.data.length}<p class="text-muted">
          No new collections meet the minimum. Sync your library to refresh genres and studios.
        </p>{/if}
      <button
        class="btn btn-primary"
        disabled={form.titles.size === 0}
        onclick={async () => {
          if (await form.generate()) uiState.closePopup();
        }}>Generate selected collections</button
      >
    {/if}
  </fieldset>
</PopupShell>
