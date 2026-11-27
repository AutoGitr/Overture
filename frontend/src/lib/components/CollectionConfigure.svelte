<script lang="ts">
  import type {
    CollectionDetail,
    MediaItemRead,
    LibrarySectionRead,
  } from "../../generated/rest/types.gen";
  import { route } from "../router/routes";
  import { revealSection } from "../utils/revealSection";
  import { CollectionDraft } from "../utils/collectionDraft.svelte";
  import { CollectionEditor } from "../utils/collectionEditor.svelte";
  import { CollectionGroupEditor } from "../utils/collectionGroupEditor.svelte";
  import { settingsState } from "../stores/settingsState.svelte";
  import CollectionDefinition from "./CollectionDefinition.svelte";
  import CollectionGroupDefinition from "./CollectionGroupDefinition.svelte";
  import CollectionGroupMembers from "./CollectionGroupMembers.svelte";
  import CollectionRulePanel from "./CollectionRulePanel.svelte";
  import CollectionSettings from "./CollectionSettings.svelte";
  import CollectionMissing from "./CollectionMissing.svelte";
  import CollectionPolicyFields from "./CollectionPolicyFields.svelte";
  import CollectionScheduleFields from "./CollectionScheduleFields.svelte";
  import CollectionSchedule from "./CollectionSchedule.svelte";
  import CollectionSetEditor from "./CollectionSetEditor.svelte";
  import CollectionMembers from "./CollectionMembers.svelte";
  import DetailForm from "./DetailForm.svelte";
  import FieldRow from "./FieldRow.svelte";
  import WorkflowSections from "./WorkflowSections.svelte";
  import PendingButton from "./PendingButton.svelte";
  import PresetUseNotice from "./PresetUseNotice.svelte";
  import DataStatus from "./DataStatus.svelte";

  let {
    collection,
    editor,
    libraryItems = [],
    groups = [],
    formId,
    libraries,
  }: {
    collection?: CollectionDetail;
    /** A collection, a new collection or set, or a group. */
    editor: CollectionEditor | CollectionDraft | CollectionGroupEditor;
    libraryItems?: MediaItemRead[];
    groups?: string[];
    formId: string;
    libraries: LibrarySectionRead[];
  } = $props();

  let groupEditor = $derived(editor instanceof CollectionGroupEditor ? editor : null);
  /** A collection, saved or new. */
  let collectionEditor = $derived(editor instanceof CollectionGroupEditor ? null : editor);
  let draft = $derived(editor instanceof CollectionDraft ? editor : null);
  let noun = $derived(groupEditor ? "Group" : "Collection");
  /** What a group page and a new set edit alike: a group's defaults, and its set. */
  let group = $derived.by(() => {
    if (groupEditor) return { form: groupEditor.form, name: groupEditor.name };
    if (draft?.kind === "set") return { form: draft.set, name: draft.setGroup };
    return null;
  });
  /** Which save is running, for its pending label. */
  let syncing = $state(false);
  let syncTitle = $derived(
    group
      ? "Save, then open Sync in Operations with only this group chosen"
      : "Save, then open Sync in Operations with only this collection chosen",
  );

  // A section link may open this view, so show the section it names once it renders.
  $effect(() => {
    if (route.hash.startsWith(`#${formId}-`)) void revealSection(route.hash.slice(1));
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
    aria-label={`Configure ${noun.toLowerCase()}`}
    onsubmit={(event) => {
      event.preventDefault();
      // Enter submits with the first button, Save.
      if (editor.blocker) return;
      syncing = event.submitter instanceof HTMLButtonElement && event.submitter.value === "sync";
      void editor.save(syncing);
    }}
  >
    <section class="setup" id={`${formId}-setup`} aria-label={`${noun} setup`} tabindex="-1">
      {#if groupEditor}
        <PresetUseNotice subject={{ group: groupEditor.name }} onreviewed={() => groupEditor.reload()} />
      {:else if collectionEditor instanceof CollectionEditor}
        <PresetUseNotice
          subject={{ collection_id: collectionEditor.collectionId }}
          onreviewed={() => collectionEditor.reload()}
        />
      {/if}
      {#if groupEditor}
        <CollectionGroupDefinition editor={groupEditor} {libraries} />
      {:else if collectionEditor}
        <CollectionDefinition editor={collectionEditor} {groups} {libraries} />
      {/if}
    </section>

    {#if group?.form.generator}
      {@const form = group.form}
      <section id={`${formId}-content`} aria-label={`${noun} content`} tabindex="-1">
        <DetailForm
          collapsible
          title="Content"
          description="What the set makes a collection for, and what every one needs."
          busy={editor.busy}
          disabled={!form.libraryIds.length}
        >
          <CollectionSetEditor
            bind:generator={form.current.generator!}
            libraryIds={form.libraryIds}
            {libraries}
            capabilities={form.capabilities}
            group={group.name}
            minimum={form.current.minimum_items ?? null}
          />
          {#if groupEditor}
            <div class="actions-row">
              <button
                type="button"
                class="btn btn-secondary"
                title="Its collections stay in the group; save to stop the set creating and updating them"
                onclick={() => (form.generator = null)}>Stop creating collections</button
              >
            </div>
          {/if}
        </DetailForm>
      </section>
    {:else if !group && collectionEditor}
      <section id={`${formId}-content`} aria-label={`${noun} content`} tabindex="-1">
        <CollectionRulePanel editor={collectionEditor} {libraries} />
      </section>
    {/if}

    {#if groupEditor}
      <section id={`${formId}-members`} aria-label={`${noun} members`} tabindex="-1">
        <CollectionGroupMembers members={groupEditor.members} set={!!groupEditor.form.generator} />
      </section>
    {:else if collection && collectionEditor instanceof CollectionEditor}
      <section id={`${formId}-members`} aria-label={`${noun} members`} tabindex="-1">
        <CollectionMembers editor={collectionEditor} {libraryItems} {libraries} />
        {#if collection.lists_missing}<CollectionMissing {collection} />{/if}
      </section>
    {/if}

    <section id={`${formId}-settings`} aria-label={`${noun} settings`} tabindex="-1">
      {#if group}
        {@const form = group.form}
        <DetailForm
          collapsible
          title="Settings"
          description="The group's defaults, which each of its collections inherits unless it sets its own."
          busy={editor.busy}
        >
          <CollectionPolicyFields
            bind:policy={form.current}
            level="group"
            defaults={form.defaults.data}
            plex={form.capabilities?.visibility ?? false}
            orders={form.orders}
            arr={form.arr}
            memberLabels={form.capabilities?.member_labels ?? false}
            filtering={!!form.generator?.smart}
          />
          <!-- Only Plex keeps empty collections, which a separator is. -->
          {#if settingsState.hasServerType("plex")}
            <FieldRow
              label="Separator"
              hint="An empty collection titled after the group, with generated art, sorted right before the group's collections. Turning it on fills in an empty Sort title with {'{group} {title}'}, which keeps them together behind it; change it to any sort title that puts the group first."
            >
              <input type="checkbox" aria-label="Separator" bind:checked={form.current.separator} />
            </FieldRow>
          {/if}
        </DetailForm>
      {:else if collectionEditor}
        <CollectionSettings editor={collectionEditor} />
      {/if}
    </section>

    <section id={`${formId}-schedule`} aria-label={`${noun} schedule`} tabindex="-1">
      {#if group}
        <DetailForm
          collapsible
          title="Active dates"
          description="When the group's collections are on the server each year."
          busy={editor.busy}
        >
          <CollectionScheduleFields
            bind:policy={group.form.current}
            level="group"
            defaults={group.form.defaults.data}
          />
        </DetailForm>
      {:else if collectionEditor}
        <CollectionSchedule editor={collectionEditor} />
      {/if}
    </section>
    <div class="actions-row" role="group" aria-label="Save">
      {#if editor.blocker}<span class="hint actions-start" role="status">{editor.blocker}</span
        >{/if}
      <PendingButton
        type="submit"
        class="btn btn-primary default-submit"
        title={editor.blocker ?? "Save in Overture; its next sync sends it to the server"}
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
        title={editor.blocker ?? syncTitle}
        pending={editor.busy}
        pendingLabel={syncing ? "Saving..." : undefined}
        disabled={!!editor.blocker}
      >
        Save and Sync
      </PendingButton>
    </div>
  </form>
</WorkflowSections>

<style>
  /* Enter submits with the first button, Save, so it comes first and sits last, in the corner. */
  .actions-row :global(.default-submit) {
    order: 1;
  }
  form {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
  }
  section {
    scroll-margin-block: var(--space-4);
  }
  .setup {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
</style>
