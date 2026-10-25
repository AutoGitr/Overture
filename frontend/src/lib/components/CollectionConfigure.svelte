<script lang="ts">
  import type {
    CollectionDetail,
    TmdbItemResult,
    MediaItemRead,
    LibrarySectionRead,
  } from "../../generated/rest/types.gen";
  import { CollectionEditor, CollectionDraft } from "../utils/collectionForms.svelte";
  import CollectionDefinition from "./CollectionDefinition.svelte";
  import CollectionRulePanel from "./CollectionRulePanel.svelte";
  import CollectionDisplaySettings from "./CollectionDisplaySettings.svelte";
  import CollectionFranchiseDiscovery from "./CollectionFranchiseDiscovery.svelte";
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

  let creationScope = $state<"single" | "multiple">("single");
</script>

{#if editor.creating && editor.mediaType === "movie"}
  <div class="scope-selector">
    <button
      type="button"
      class="btn btn-sm"
      class:btn-secondary={creationScope === "single"}
      class:btn-ghost={creationScope !== "single"}
      onclick={() => (creationScope = "single")}
    >
      Single Collection
    </button>
    <button
      type="button"
      class="btn btn-sm"
      class:btn-secondary={creationScope === "multiple"}
      class:btn-ghost={creationScope !== "multiple"}
      onclick={() => (creationScope = "multiple")}
    >
      Auto-discover All Franchises (Multiple)
    </button>
  </div>
{/if}

{#if creationScope === "multiple" && editor.creating}
  <CollectionFranchiseDiscovery {libraries} />
{:else}
  <form
    id={formId}
    aria-label="Configure collection"
    onsubmit={(event) => {
      event.preventDefault();
      void editor.save();
    }}
  >
    <section id={`${formId}-general`} aria-label="General" tabindex="-1">
      <CollectionDefinition bind:editor {groups} {libraries} />
    </section>

    {#if editor.sourceType !== "manual"}
      <section id={`${formId}-builder`} aria-label="Builder" tabindex="-1">
        <CollectionRulePanel bind:editor />
      </section>
    {/if}

    {#if editor instanceof CollectionDraft}
      {@const draft = editor}
      <section id={`${formId}-members`} aria-label="Initial members" tabindex="-1">
        <DetailSection
          title="Members"
          description="Choose library items for a manual collection, or let the builder resolve its source when saving."
        >
          <span class="badge">{draft.memberIds.size} selected</span>
          {#if draft.manualMembersAllowed}
            <label class="form-label">
              Search members
              <input type="search" disabled={!draft.libraryId} bind:value={draft.memberSearch} />
            </label>
            {#each draft.availableMembers(libraryItems) as item (item.id)}
              <label class="form-row">
                <input
                  type="checkbox"
                  checked={draft.memberIds.has(item.id)}
                  disabled={draft.busy}
                  onchange={() => draft.toggle(item.id)}
                />
                {item.title}
              </label>
            {/each}
          {/if}
        </DetailSection>
      </section>
    {/if}

    <section id={`${formId}-display`} aria-label="Display" tabindex="-1">
      <CollectionDisplaySettings bind:editor {libraries} />
    </section>
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
{/if}

<style>
  .scope-selector {
    display: flex;
    gap: var(--space-2);
    padding: var(--space-2);
    background: var(--surface-2);
    border-radius: var(--radius-md);
    width: fit-content;
    margin-bottom: var(--space-2);
  }
  form {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
  }
  section {
    scroll-margin-block: var(--space-4);
  }
</style>
