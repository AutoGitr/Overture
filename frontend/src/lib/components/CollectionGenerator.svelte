<script lang="ts">
  import { untrack } from "svelte";
  import { CollectionGenerator } from "../utils/collectionForms.svelte";
  import type { LibrarySectionRead, MediaType } from "../../generated/rest/types.gen";
  import CollectionPolicyFields from "./CollectionPolicyFields.svelte";
  let {
    libraries,
    mediaType,
    libraryId,
  }: { libraries: LibrarySectionRead[]; mediaType: MediaType; libraryId: string } = $props();
  let open = $state(false);
  const form = new CollectionGenerator(
    untrack(() => mediaType),
    () => libraryId,
  );
</script>

<details class="form-wide" bind:open>
  <summary>Generate collections</summary>
  {#if open}
    <p class="text-muted">
      Build dynamic collections from your library. Review the preview and select the collections to
      create.
    </p>
    <fieldset
      class="options-col"
      disabled={form.generateRequest.isPending || form.preview.isPending}
    >
      <legend>Collection presets</legend>
      <label class="form-label"
        >Generator library<select bind:value={form.libraryId} onchange={() => form.resetPreview()}
          ><option value="">Select a library</option
          >{#each libraries as library (library.id)}<option value={library.id}
              >{library.title}</option
            >{/each}</select
        ></label
      >
      <label class="form-label"
        >Group by<select bind:value={form.preset} onchange={() => form.resetPreview()}
          >{#if form.mediaType === "movie"}<option value="tmdb_collections">TMDB Collections</option
            >{/if}<option value="decades">Decades</option><option value="genres">Genres</option
          ><option value="studios">Studios</option></select
        ></label
      >
      <label class="form-label"
        >Target collection group
        <input
          maxlength="200"
          bind:value={form.collectionGroup}
          placeholder="Preset default"
          onchange={() => form.resetPreview()}
        />
      </label>
      <CollectionPolicyFields policy={form} prefix="Generator " />
      <label class="form-label"
        >Sort title template
        <input
          maxlength="200"
          bind:value={form.sort_title_format}
          placeholder="Inherit group or global template"
        />
        <span class="hint">Use &#123;title&#125; and &#123;group&#125;.</span>
      </label>
      <button
        type="button"
        class="btn"
        disabled={!form.libraryId}
        onclick={() => void form.previewCollections()}>Preview collections</button
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
            No new collections meet the minimum. Sync your library to refresh franchise memberships,
            genres and studios.
          </p>{/if}
        <button
          type="button"
          class="btn btn-primary"
          disabled={form.titles.size === 0}
          onclick={async () => {
            if (await form.generate()) form.resetPreview();
          }}>Generate selected collections</button
        >
      {/if}
    </fieldset>
  {/if}
</details>
