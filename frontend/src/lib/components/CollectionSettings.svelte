<script lang="ts">
  import DetailForm from "./DetailForm.svelte";
  import type { CollectionEditor } from "../utils/collectionForms.svelte";
  let { editor, groups }: { editor: CollectionEditor; groups: string[] } = $props();
  const groupListId = $props.id();
  let plex = $derived(editor.collection.server_type === "plex");
</script>

<DetailForm
  title="General & Server Display"
  description="Manage the collection's metadata and how it appears in your library."
  busy={editor.busy}
>
  <label class="form-label"
    >Title <input required maxlength="200" bind:value={editor.title} /></label
  >
  <div class="options-col">
    <label class="form-label"
      >Sort title <input maxlength="200" bind:value={editor.sortTitle} /></label
    >
    <div class="form-row">
      {#each ["!", "+", "01_"] as prefix (prefix)}<button
          type="button"
          class="btn btn-ghost btn-sm"
          onclick={() => (editor.sortTitle = prefix + (editor.sortTitle || editor.title))}
          >{prefix}</button
        >{/each}
    </div>
  </div>
  <label class="form-label form-wide"
    >Summary <textarea maxlength="10000" bind:value={editor.summary}></textarea></label
  >
  <label class="form-label"
    >Collection Group
    <input
      list={groupListId}
      maxlength="200"
      bind:value={editor.collectionGroup}
      placeholder="Ungrouped"
    />
    <datalist id={groupListId}
      >{#each groups as group (group)}<option value={group}></option>{/each}</datalist
    >
  </label>
  {#if plex}
    <label class="form-label"
      >Visibility <select bind:value={editor.collectionMode}
        ><option value={null}>Inherit global default</option><option value="default"
          >Library default</option
        ><option value="hide_items">Hide items</option><option value="show_items"
          >Show collection and items</option
        ><option value="hide">Hide collection</option></select
      ></label
    >
    <label class="form-row"
      ><input type="checkbox" bind:checked={editor.visibleHome} />Visible on home</label
    >
  {/if}
</DetailForm>
