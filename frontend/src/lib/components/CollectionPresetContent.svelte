<script lang="ts">
  import type { CollectionDraft } from "../utils/collectionForms.svelte";
  import DetailForm from "./DetailForm.svelte";
  import PendingButton from "./PendingButton.svelte";
  import CollectionPolicyFields from "./CollectionPolicyFields.svelte";

  let { editor }: { editor: CollectionDraft } = $props();
</script>

<DetailForm
  title="Content"
  description="Preview values in this library, then choose the collections to create. Each collection continues to update from its library filter. Existing collections are kept; matching titles are reported for review."
  busy={editor.busy}
  collapsible
  expanded
>
  <div class="form-wide options-col">
    <PendingButton
      type="button"
      class="btn btn-secondary"
      pending={editor.presetLoading}
      pendingLabel="Previewing..."
      disabled={!editor.libraryId}
      onclick={() => void editor.previewPreset()}
    >
      Preview collections
    </PendingButton>
    {#if editor.presetEntries.length}
      <div class="form-row">
        <button
          type="button"
          class="btn btn-ghost btn-sm"
          onclick={() => (editor.selectedKeys = editor.presetEntries.map((entry) => entry.key))}
          >Select all</button
        >
        <button
          type="button"
          class="btn btn-ghost btn-sm"
          onclick={() => (editor.selectedKeys = [])}>Clear selection</button
        >
        <span class="hint">{editor.selectedKeys.length} selected</span>
      </div>
      {#each editor.presetEntries as entry (entry.key)}
        <label class="form-row">
          <input type="checkbox" value={entry.key} bind:group={editor.selectedKeys} />
          {entry.title} ({entry.member_count}
          {entry.member_count === 1 ? "member" : "members"})
        </label>
        {#if editor.presetErrors[entry.key]}<p role="alert">
            {entry.title}: {editor.presetErrors[entry.key]}
          </p>{/if}
      {/each}
    {:else if editor.hasPresetPreview}<p class="hint">
        No matching values were found in this library.
      </p>
    {:else}<p class="hint">
        Choose a library and preview its available values. No collections are created until you
        submit.
      </p>{/if}
  </div>
  <CollectionPolicyFields policy={editor.rule} defaults={editor.defaults.data} section="sync" />
</DetailForm>
