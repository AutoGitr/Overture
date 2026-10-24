<script lang="ts">
  import type {
    CollectionDetail,
    MediaItemRead,
    LibrarySectionRead,
  } from "../../generated/rest/types.gen";
  import { CollectionEditor, CollectionDraft } from "../utils/collectionForms.svelte";
  import CollectionSettings from "./CollectionSettings.svelte";
  import CollectionRulePanel from "./CollectionRulePanel.svelte";
  import CollectionMembers from "./CollectionMembers.svelte";
  import DetailSection from "./DetailSection.svelte";

  let {
    collection,
    editor,
    libraryItems,
    groups,
    formId,
    libraries,
  }: {
    collection?: CollectionDetail;
    editor: CollectionEditor | CollectionDraft;
    libraryItems: MediaItemRead[];
    groups: string[];
    formId: string;
    libraries: LibrarySectionRead[];
  } = $props();
</script>

<form
  id={formId}
  aria-label="Configure collection"
  onsubmit={(event) => {
    event.preventDefault();
    void editor.save();
  }}
>
  <section id={`${formId}-general`} aria-label="General" tabindex="-1">
    <CollectionSettings {editor} {groups} {libraries} />
  </section>
  <section id={`${formId}-builder`} aria-label="Builder" tabindex="-1">
    <CollectionRulePanel {editor} />
  </section>
  {#if editor instanceof CollectionDraft}
    <section id={`${formId}-members`} aria-label="Initial members" tabindex="-1">
      <DetailSection
        title="Members"
        description="Choose library items for a manual collection, or let the builder resolve its source when saving."
      >
        <span class="badge">{editor.memberIds.size} selected</span>
        {#if editor.manualMembersAllowed}
          <label class="form-label"
            >Search members<input
              type="search"
              disabled={!editor.libraryId}
              bind:value={editor.memberSearch}
            /></label
          >
          {#each editor.availableMembers(libraryItems) as item (item.id)}
            <label class="form-row"
              ><input
                type="checkbox"
                checked={editor.memberIds.has(item.id)}
                disabled={editor.busy}
                onchange={() => editor.toggle(item.id)}
              />{item.title}</label
            >
          {/each}
        {/if}
      </DetailSection>
    </section>
  {/if}
</form>
{#if collection && editor instanceof CollectionEditor}
  <section id={`${formId}-members`} aria-label="Resolved members" tabindex="-1">
    <CollectionMembers members={collection.members} {editor} {libraryItems} />
  </section>
  <DetailSection
    title="Danger Zone"
    description="Deleting this collection preserves its underlying movies, shows and media files."
  >
    <button
      type="button"
      class="btn btn-danger"
      disabled={editor.busy}
      onclick={() => void editor.delete()}>Delete collection</button
    >
  </DetailSection>
{/if}

<style>
  form {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
  }
  section {
    scroll-margin-block: var(--space-4);
  }
</style>
