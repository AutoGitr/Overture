<script lang="ts">
  import type { CollectionEditor } from "../utils/collectionForms.svelte";
  let { editor }: { editor: CollectionEditor } = $props();
  let plex = $derived(editor.collection.server_type === "plex");
</script>

<form
  class="options-col"
  onsubmit={(event) => {
    event.preventDefault();
    void editor.save();
  }}
>
  <fieldset class="options-col" disabled={editor.busy}>
    <legend>Collection settings</legend>
    <label class="form-label"
      >Title <input required maxlength="200" bind:value={editor.options.title} /></label
    >
    <label class="form-label"
      >Summary <textarea maxlength="10000" bind:value={editor.options.summary}></textarea></label
    >
    <label class="form-label"
      >Sort title <input maxlength="200" bind:value={editor.options.sort_title} /></label
    >
    <div class="form-row">
      {#each ["!", "+", "01_"] as prefix (prefix)}<button
          type="button"
          class="btn btn-ghost btn-sm"
          onclick={() =>
            (editor.options.sort_title =
              prefix + (editor.options.sort_title || editor.options.title))}>{prefix}</button
        >{/each}
    </div>
    {#if plex}
      <label class="form-label"
        >Visibility <select bind:value={editor.options.collection_mode}
          ><option value={null}>Inherit global default</option><option value="default"
            >Library default</option
          ><option value="hide_items">Hide items</option><option value="show_items"
            >Show collection and items</option
          ><option value="hide">Hide collection</option></select
        ></label
      >
      <label class="form-row"
        ><input type="checkbox" bind:checked={editor.options.visible_home} />Visible on home</label
      >
    {/if}
    <label class="form-label"
      >Member order <select bind:value={editor.options.order_type}
        ><option value="release">Release date</option><option value="alpha">Alphabetical</option
        >{#if plex}<option value="custom">Custom</option>{/if}</select
      ></label
    >
    <button class="btn btn-primary" type="submit">Save collection settings</button>
  </fieldset>
</form>
<button class="btn btn-danger" disabled={editor.busy} onclick={() => void editor.delete()}
  >Delete collection</button
>
