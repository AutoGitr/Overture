<script lang="ts">
  import type {
    CollectionDetail,
    TmdbItemResult,
    MediaItemRead,
    LibrarySectionRead,
  } from "../../generated/rest/types.gen";
  import { route } from "../router/routes";
  import { CollectionEditor, CollectionDraft } from "../utils/collectionForms.svelte";
  import CollectionDefinition from "./CollectionDefinition.svelte";
  import CollectionRulePanel from "./CollectionRulePanel.svelte";
  import CollectionSettings from "./CollectionSettings.svelte";
  import CollectionGroupDefaults from "./CollectionGroupDefaults.svelte";
  import CollectionSchedule from "./CollectionSchedule.svelte";
  import CollectionSetEditor from "./CollectionSetEditor.svelte";
  import CollectionMembers from "./CollectionMembers.svelte";
  import DetailForm from "./DetailForm.svelte";
  import DetailSection from "./DetailSection.svelte";
  import WorkflowSections from "./WorkflowSections.svelte";
  import PendingButton from "./PendingButton.svelte";
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

  let onServer = $derived(!!collection && !collection.withheld);
  let set = $derived(editor instanceof CollectionDraft && editor.kind === "set" ? editor : null);
  /** Which save is running, for its pending label. */
  let syncing = $state(false);

  // A section link may open this view, so show the section it names once it renders.
  $effect(() => {
    const section = route.hash.startsWith(`#${formId}-`)
      ? document.getElementById(route.hash.slice(1))
      : null;
    section?.querySelector<HTMLButtonElement>('button[aria-expanded="false"]')?.click();
    section?.focus();
  });
</script>

<WorkflowSections>
  <DataStatus
    label="collection defaults"
    error={editor.defaults.error}
    loading={editor.defaults.isFetching}
    hasData={editor.defaults.data !== undefined}
    onretry={() => editor.defaults.refetch()}
  />
  <DataStatus
    label="collection options"
    error={editor.capabilities.error}
    loading={editor.capabilities.isFetching}
    hasData={editor.capabilities.data !== undefined}
    onretry={() => editor.capabilities.refetch()}
  />
  <form
    id={formId}
    aria-label="Configure collection"
    onsubmit={(event) => {
      event.preventDefault();
      // Enter submits with the first button, Save.
      syncing = event.submitter instanceof HTMLButtonElement && event.submitter.value === "sync";
      void editor.save(syncing);
    }}
  >
    <section id={`${formId}-setup`} aria-label="Collection setup" tabindex="-1">
      <CollectionDefinition {editor} {groups} {libraries} />
    </section>

    {#if set}
      <section id={`${formId}-content`} aria-label="Set collections" tabindex="-1">
        <DetailForm
          collapsible
          expanded
          title="Collections"
          description="Choose what the set creates a collection for. Preview to see the collections before creating them."
          busy={set.busy}
        >
          <CollectionSetEditor
            generator={set.generator}
            libraryId={set.libraryId}
            mediaType={set.mediaType}
            capabilities={set.capabilities.data}
            group={set.collectionGroup}
            minimum={set.setPolicy.minimum_items ?? null}
          />
        </DetailForm>
      </section>
      <section id={`${formId}-settings`} aria-label="Set defaults" tabindex="-1">
        <DetailForm
          collapsible
          title="Defaults"
          description="The group's defaults, which every collection in the set inherits."
          busy={set.busy}
        >
          <CollectionGroupDefaults
            policy={set.setPolicy}
            defaults={set.defaults.data}
            capabilities={set.capabilities.data}
            smart={!!set.generator.smart}
          />
        </DetailForm>
      </section>
    {:else}
      <section id={`${formId}-content`} aria-label="Collection content" tabindex="-1">
        <CollectionRulePanel {editor} />
      </section>

      {#if collection && editor instanceof CollectionEditor}
        <section id={`${formId}-members`} aria-label="Collection members" tabindex="-1">
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

      <section id={`${formId}-settings`} aria-label="Collection settings" tabindex="-1">
        <CollectionSettings {editor} />
      </section>

      <section id={`${formId}-schedule`} aria-label="Collection schedule" tabindex="-1">
        <CollectionSchedule {editor} />
      </section>
    {/if}
    <div class="form-row" role="group" aria-label="Save">
      <PendingButton
        type="submit"
        class="btn btn-primary"
        title="Save in Overture without changing the server"
        pending={editor.busy}
        pendingLabel={syncing ? undefined : "Saving..."}
        disabled={editor instanceof CollectionDraft && !editor.canSubmit}
      >
        Save
      </PendingButton>
      <PendingButton
        type="submit"
        value="sync"
        class="btn btn-secondary"
        pending={editor.busy}
        pendingLabel={syncing ? (onServer ? "Syncing..." : "Creating...") : undefined}
        disabled={editor instanceof CollectionDraft && !editor.canSubmit}
      >
        {onServer ? "Save and Sync" : "Save and Create"}
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
