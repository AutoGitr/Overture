<script lang="ts">
  import type {
    CollectionDetail,
    TmdbItemResult,
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
    editor = $bindable(),
    libraryItems,
    groups,
    formId,
    libraries,
    sourceRoster = [],
  }: {
    collection?: CollectionDetail;
    sourceRoster?: TmdbItemResult[];
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
    <CollectionSettings bind:editor {groups} {libraries} />
  </section>
  <section id={`${formId}-builder`} aria-label="Builder" tabindex="-1">
    <CollectionRulePanel bind:editor />
  </section>
  {#if editor instanceof CollectionDraft}
    {@const draft = editor}
    <section id={`${formId}-members`} aria-label="Initial members" tabindex="-1">
      <DetailSection
        title="Members"
        description="Choose library items for a manual collection, or let the builder resolve its source when saving."
      >
        <span class="badge">{draft.memberIds.size} selected</span>
        {#if draft.manualMembersAllowed}
          <label class="form-label"
            >Search members<input
              type="search"
              disabled={!draft.libraryId}
              bind:value={draft.memberSearch}
            /></label
          >
          {#each draft.availableMembers(libraryItems) as item (item.id)}
            <label class="form-row"
              ><input
                type="checkbox"
                checked={draft.memberIds.has(item.id)}
                disabled={draft.busy}
                onchange={() => draft.toggle(item.id)}
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
    {#if sourceRoster.length}
      <DetailSection
        title="Source roster"
        description="Movies in the TMDB franchise, including titles missing from your library."
      >
        <CollectionMembers members={sourceRoster} />
      </DetailSection>
    {/if}
  </section>
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
