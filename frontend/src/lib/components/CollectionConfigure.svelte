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
  import CollectionMembers from "./CollectionMembers.svelte";
  import DetailSection from "./DetailSection.svelte";
  import WorkflowSections from "./WorkflowSections.svelte";
  import PendingButton from "./PendingButton.svelte";
  import CollectionPresetContent from "./CollectionPresetContent.svelte";
  import DataStatus from "./DataStatus.svelte";

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

<WorkflowSections>
  <DataStatus
    label="collection defaults"
    error={editor.defaults.error}
    loading={editor.defaults.isFetching}
    hasData={editor.defaults.data !== undefined}
    onretry={() => editor.defaults.refetch()}
  />
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
      {#if editor instanceof CollectionDraft && editor.generating}
        <section id={`${formId}-content`} aria-label="Content" tabindex="-1">
          <CollectionPresetContent {editor} />
        </section>
      {:else if editor.sourceType !== "unmanaged"}
        <section id={`${formId}-content`} aria-label="Content" tabindex="-1">
          <CollectionRulePanel {editor} />
        </section>
      {/if}

      {#if collection && editor instanceof CollectionEditor}
        <section id={`${formId}-members`} aria-label="Resolved members" tabindex="-1">
          <CollectionMembers members={collection.members} {editor} {libraryItems} />
          {#if sourceRoster.length}
            <DetailSection
              collapsible
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
        pendingLabel={discovering
          ? "Discovering..."
          : editor.creating
            ? "Creating..."
            : "Saving..."}
        disabled={editor instanceof CollectionDraft && !editor.canSubmit}
      >
        {discovering
          ? "Discover & Create"
          : editor instanceof CollectionDraft && editor.generating
            ? "Create selected collections"
            : editor.creating
              ? "Create"
              : "Save"}
      </PendingButton>
    </div>
  </form>
</WorkflowSections>

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
