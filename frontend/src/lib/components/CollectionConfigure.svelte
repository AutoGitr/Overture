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
  import CollectionSchedule from "./CollectionSchedule.svelte";
  import CollectionGroupSettings from "./CollectionGroupSettings.svelte";
  import CollectionMembers from "./CollectionMembers.svelte";
  import DetailSection from "./DetailSection.svelte";
  import DetailForm from "./DetailForm.svelte";
  import PendingButton from "./PendingButton.svelte";

  let {
    collection,
    editor,
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

  let discovering = $derived(editor instanceof CollectionDraft && editor.discovering);
</script>

<form
  id={formId}
  aria-label="Configure collection"
  onsubmit={(event) => {
    event.preventDefault();
    void editor.save();
  }}
>
  <section id={`${formId}-setup`} aria-label="Setup" tabindex="-1">
    <CollectionDefinition {editor} {groups} {libraries} />
  </section>

  {#if discovering && editor instanceof CollectionDraft}
    <section id={`${formId}-content`} aria-label="Content" tabindex="-1">
      <CollectionFranchiseDiscovery {editor} />
    </section>
  {:else}
    {#if editor.sourceType !== "manual"}
      <section id={`${formId}-content`} aria-label="Content" tabindex="-1">
        <CollectionRulePanel {editor} />
      </section>
    {/if}

    {#if editor instanceof CollectionDraft && editor.manualMembersAllowed}
      {@const draft = editor}
      <section id={`${formId}-members`} aria-label="Initial members" tabindex="-1">
        <DetailForm
          title="Members"
          busy={draft.busy}
          description={draft.sourceType === "manual"
            ? "Select items from this library to include in the collection."
            : "These items are kept alongside source results when using Append."}
        >
          <div class="options-col form-wide">
            <span class="badge">{draft.memberIds.size} selected</span>
            <label class="form-label">
              Search members
              <input type="search" disabled={!draft.libraryId} bind:value={draft.memberSearch} />
            </label>
            {#each draft.availableMembers(libraryItems) as item (item.id)}
              <label class="form-row">
                <input
                  type="checkbox"
                  checked={draft.memberIds.has(item.id)}
                  onchange={() => draft.toggle(item.id)}
                />
                {item.title}
              </label>
            {:else}
              <p class="text-muted">
                {draft.libraryId
                  ? "No matching library items."
                  : "Select a library in Collection Setup to choose members."}
              </p>
            {/each}
          </div>
        </DetailForm>
      </section>
    {:else if collection && editor instanceof CollectionEditor}
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

    <section id={`${formId}-display`} aria-label="Collection display" tabindex="-1">
      <CollectionDisplaySettings {editor} />
    </section>
  {/if}

  <section id={`${formId}-schedule`} aria-label="Collection schedule" tabindex="-1">
    <CollectionSchedule {editor} />
  </section>
  <div class="form-row" role="group" aria-label="Collection form actions">
    <PendingButton
      type="submit"
      class="btn btn-primary"
      pending={editor.busy}
      pendingLabel={discovering ? "Discovering..." : editor.creating ? "Creating..." : "Saving..."}
      disabled={editor instanceof CollectionDraft && !editor.canSubmit}
    >
      {discovering ? "Discover & Create" : editor.creating ? "Create" : "Save"}
    </PendingButton>
  </div>
</form>

{#if !discovering && editor.collectionGroup.trim()}
  <section id={`${formId}-group`} aria-label="Group defaults" tabindex="-1">
    <CollectionGroupSettings
      group={editor.collectionGroup.trim()}
      mediaType={editor.mediaType}
      serverType={editor.serverType}
      {libraries}
    />
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
