<script lang="ts">
  import type {
    CollectionDetail,
    MediaItemRead,
    LibrarySectionRead,
  } from "../../generated/rest/types.gen";
  import { route } from "../router/routes";
  import { revealSection } from "../utils/revealSection";
  import { CollectionEditor, CollectionDraft } from "../utils/collectionForms.svelte";
  import CollectionDefinition from "./CollectionDefinition.svelte";
  import CollectionRulePanel from "./CollectionRulePanel.svelte";
  import CollectionSettings from "./CollectionSettings.svelte";
  import CollectionMissing from "./CollectionMissing.svelte";
  import CollectionPolicyFields from "./CollectionPolicyFields.svelte";
  import CollectionScheduleFields from "./CollectionScheduleFields.svelte";
  import { availableOrders } from "../utils/collectionCriteria";
  import CollectionSchedule from "./CollectionSchedule.svelte";
  import CollectionSetEditor from "./CollectionSetEditor.svelte";
  import CollectionMembers from "./CollectionMembers.svelte";
  import DetailForm from "./DetailForm.svelte";
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
  }: {
    collection?: CollectionDetail;
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
    if (route.hash.startsWith(`#${formId}-`)) revealSection(route.hash.slice(1));
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
      if (editor.blocker) return;
      syncing = event.submitter instanceof HTMLButtonElement && event.submitter.value === "sync";
      void editor.save(syncing);
    }}
  >
    <section id={`${formId}-setup`} aria-label="Collection setup" tabindex="-1">
      <CollectionDefinition {editor} {groups} {libraries} />
    </section>

    <section id={`${formId}-content`} aria-label="Collection content" tabindex="-1">
      {#if set}
        <DetailForm
          collapsible
          expanded
          title="Content"
          description="What the set makes a collection for, and what every one needs."
          busy={set.busy}
          disabled={!set.libraryIds.length}
        >
          <CollectionSetEditor
            generator={set.generator}
            libraryIds={set.libraryIds}
            {libraries}
            mediaType={set.mediaType}
            capabilities={set.capabilities.data}
            group={set.setGroup}
            minimum={set.setPolicy.minimum_items ?? null}
          />
        </DetailForm>
      {:else}
        <CollectionRulePanel {editor} />
      {/if}
    </section>

    {#if collection && editor instanceof CollectionEditor}
      <section id={`${formId}-members`} aria-label="Collection members" tabindex="-1">
        <CollectionMembers members={collection.members} {editor} {libraryItems} />
        {#if collection.rule}<CollectionMissing {collection} />{/if}
      </section>
    {/if}

    <section id={`${formId}-settings`} aria-label="Collection settings" tabindex="-1">
      {#if set}
        <DetailForm
          collapsible
          title="Settings"
          description="The set's group defaults, which each of its collections inherits."
          busy={set.busy}
          disabled={!set.libraryIds.length}
        >
          <CollectionPolicyFields
            policy={set.setPolicy}
            level="group"
            defaults={set.defaults.data}
            plex={set.capabilities.data?.visibility ?? false}
            orders={availableOrders(set.capabilities.data, !!set.generator.smart)}
            arr={set.capabilities.data?.arr
              ? set.mediaType === "movie"
                ? "Radarr"
                : "Sonarr"
              : null}
            memberLabels={set.capabilities.data?.member_labels ?? false}
          />
        </DetailForm>
      {:else}
        <CollectionSettings {editor} />
      {/if}
    </section>

    <section id={`${formId}-schedule`} aria-label="Collection schedule" tabindex="-1">
      {#if set}
        <DetailForm
          collapsible
          title="Schedule"
          description="When the set syncs, and when its collections are active each year."
          busy={set.busy}
          disabled={!set.libraryIds.length}
        >
          <CollectionScheduleFields
            policy={set.setPolicy}
            level="group"
            defaults={set.defaults.data}
          />
        </DetailForm>
      {:else}
        <CollectionSchedule {editor} />
      {/if}
    </section>
    <div class="form-row" role="group" aria-label="Save">
      <PendingButton
        type="submit"
        class="btn btn-primary"
        title={editor.blocker ?? "Save in Overture without changing the server"}
        pending={editor.busy}
        pendingLabel={syncing ? undefined : "Saving..."}
        disabled={!!editor.blocker}
      >
        Save
      </PendingButton>
      <PendingButton
        type="submit"
        value="sync"
        class="btn btn-secondary"
        title={editor.blocker ?? undefined}
        pending={editor.busy}
        pendingLabel={syncing ? (onServer ? "Syncing..." : "Creating...") : undefined}
        disabled={!!editor.blocker}
      >
        {onServer ? "Save and Sync" : "Save and Create"}
      </PendingButton>
      {#if editor.blocker}<span class="hint" role="status">{editor.blocker}</span>{/if}
    </div>
  </form>
  {#if collection && editor instanceof CollectionEditor}
    {@const savedEditor = editor}
    <DetailForm
      title="Delete collection"
      description="Choose where to remove the collection. Media files are always kept."
      busy={editor.busy}
      collapsible
    >
      <p class="hint">
        Keeping the Overture configuration lets a later manual or scheduled sync recreate the
        server collection.
      </p>
      <button
        type="button"
        class="btn btn-danger"
        disabled={!onServer}
        onclick={() => void savedEditor.delete("server")}>Delete from server only</button
      >
      <button
        type="button"
        class="btn btn-danger"
        onclick={() => void savedEditor.delete("both")}>Delete from Overture and server</button
      >
    </DetailForm>
  {/if}
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
