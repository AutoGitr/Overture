<script lang="ts">
  import { UNGROUPED_GROUP } from "../../generated/settings";

  import { uiState } from "../stores/uiState.svelte";
  import DetailForm from "./DetailForm.svelte";
  import FieldRow from "./FieldRow.svelte";
  import SegmentedControl from "./SegmentedControl.svelte";
  import { CollectionDraft, type CollectionEditor } from "../utils/collectionForms.svelte";
  import Notice from "./Notice.svelte";
  import SetDimensionField from "./SetDimensionField.svelte";
  import type { LibrarySectionRead } from "../../generated/rest/types.gen";

  let {
    editor,
    groups,
    libraries,
  }: {
    editor: CollectionEditor | CollectionDraft;
    groups: string[];
    libraries: LibrarySectionRead[];
  } = $props();

  const id = $props.id();
  const NEW_GROUP = "__new__";
  const KINDS = [
    ["collection", "One collection"],
    ["set", "One per value"],
  ] as const;
  let draft = $derived(editor instanceof CollectionDraft ? editor : null);
  let creatingSet = $derived(draft?.kind === "set");
  let libraryGroups = $derived(
    (
      [
        ["movie", "Movie libraries"],
        ["show", "Show libraries"],
      ] as const
    )
      .map(([mediaType, label]) => ({
        label,
        libraries: libraries.filter((library) => library.media_type === mediaType),
      }))
      .filter((group) => group.libraries.length > 0),
  );
</script>

<DetailForm
  collapsible
  expanded
  title="Setup"
  description={creatingSet
    ? "One collection per value in the library, such as each decade, kept up to date."
    : "Which libraries it spans, its title and its group."}
  busy={editor.busy}
>
  {#if draft}
    {@const form = draft}
    <FieldRow label="Create">
      <SegmentedControl
        label="Create"
        options={KINDS}
        bind:value={() => form.kind, (kind) => form.selectKind(kind)}
      />
    </FieldRow>
    {#if creatingSet}
      <SetDimensionField
        value={form.generator.dimension}
        dimensions={form.dimensions}
        onchoose={(dimension) => form.chooseDimension(dimension)}
      />
    {/if}
  {/if}
  <fieldset class="libraries" disabled={editor.generated}>
    <legend class="form-label">Libraries</legend>
    {#each libraryGroups as group (group.label)}
      <div class="library-group" role="group" aria-label={group.label}>
        {#each group.libraries as library (library.id)}
          <label class="form-row">
            <input
              type="checkbox"
              checked={editor.libraryIds.includes(library.id)}
              onchange={(event) => editor.setLibrary(library.id, event.currentTarget.checked)}
            />
            {library.title}
          </label>
        {/each}
      </div>
    {/each}
    {#if editor.libraryIds.length > 1 && !creatingSet}
      <span class="hint"
        >{editor.capabilities.data?.spans_libraries
          ? "One collection on the server holds them all."
          : "Plex keeps a collection in one library, so each gets its own, kept alike."}</span
      >
    {/if}
  </fieldset>

  {#if draft && creatingSet}
    {@const form = draft}
    <FieldRow
      label="Title template"
      for={`${id}-title`}
      hint={"{value} becomes each value, such as 1990 or Action."}
    >
      <input
        id={`${id}-title`}
        required
        maxlength="200"
        bind:value={form.generator.title_format}
        placeholder={"{value}"}
      />
    </FieldRow>
    <FieldRow
      label="Group"
      for={`${id}-group`}
      hint="A set is a group whose collections it creates; Split by names it. A group that holds collections can become a set; one that already is a set cannot."
    >
      <input
        id={`${id}-group`}
        maxlength="200"
        bind:value={form.collectionGroup}
        placeholder="e.g. Decades"
        list={`${id}-groups`}
      />
      <datalist id={`${id}-groups`}>
        {#each groups as group (group)}<option value={group}></option>{/each}
      </datalist>
    </FieldRow>
    {#each form.setNotices as notice (notice.title)}
      <Notice
        tone={notice.tone}
        title={notice.title}
        message={notice.message}
        action={notice.group
          ? {
              label: "Open group settings",
              run: () => uiState.openCollectionGroups(notice.group),
            }
          : undefined}
      />
    {/each}
  {:else}
    <FieldRow label="Title" for={`${id}-title`}>
      <input
        id={`${id}-title`}
        required
        maxlength="200"
        bind:value={editor.title}
        disabled={editor.generated}
        placeholder="Collection title"
      />
    </FieldRow>

    <FieldRow
      label="Group"
      for={`${id}-group`}
      hint={editor.generated
        ? "Its group's set titles this collection."
        : (draft?.groupHint ?? "The collection inherits the group's defaults.")}
    >
      <select
        id={`${id}-group`}
        disabled={editor.generated}
        value={editor.collectionGroup || UNGROUPED_GROUP}
        onchange={(event) => {
          if (event.currentTarget.value !== NEW_GROUP) {
            editor.collectionGroup = event.currentTarget.value;
            return;
          }
          // The select keeps showing the current group until the popup creates one.
          event.currentTarget.value = editor.collectionGroup || UNGROUPED_GROUP;
          uiState.openCollectionGroups("", (name, replacement) => {
            if (!name || editor.collectionGroup === name) editor.collectionGroup = replacement;
          });
        }}
      >
        {#if !groups.includes(UNGROUPED_GROUP)}<option value={UNGROUPED_GROUP}>{UNGROUPED_GROUP}</option>{/if}
        {#if editor.collectionGroup && editor.collectionGroup !== UNGROUPED_GROUP && !groups.includes(editor.collectionGroup)}
          <option value={editor.collectionGroup || UNGROUPED_GROUP}>{editor.collectionGroup}</option>
        {/if}
        {#each groups as group (group)}<option value={group}>{group}</option>{/each}
        <option value={NEW_GROUP}>Create new group...</option>
      </select>
    </FieldRow>
  {/if}

</DetailForm>

<style>
  .libraries,
  .library-group {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2) var(--space-4);
    min-width: 0;
    margin: 0;
    padding: 0;
    border: 0;
  }

  .libraries legend {
    width: 100%;
    padding: 0;
  }

  .library-group {
    width: 100%;
  }
</style>
