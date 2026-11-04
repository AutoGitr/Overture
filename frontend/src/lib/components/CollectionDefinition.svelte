<script lang="ts">
  import { UNGROUPED_GROUP } from "../../generated/settings";

  import { uiState } from "../stores/uiState.svelte";
  import DetailForm from "./DetailForm.svelte";
  import FieldRow from "./FieldRow.svelte";
  import SegmentedControl from "./SegmentedControl.svelte";
  import { CollectionDraft, type CollectionEditor } from "../utils/collectionForms.svelte";
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
</script>

<DetailForm
  collapsible
  expanded
  title="Setup"
  description={creatingSet
    ? "One collection per value in the library, such as each decade, kept up to date."
    : "Where the collection lives, its title and its group."}
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
    <fieldset class="libraries">
      <legend class="form-label">Libraries</legend>
      {#each libraries as library (library.id)}
        <label class="form-row">
          <input
            type="checkbox"
            checked={form.libraryIds.includes(library.id)}
            onchange={(event) =>
              (form.libraryIds = event.currentTarget.checked
                ? [...form.libraryIds, library.id]
                : form.libraryIds.filter((libraryId) => libraryId !== library.id))}
          />
          {library.title}
        </label>
      {/each}
      {#if form.linked}
        <span class="hint"
          >Several libraries make a set with this collection in each, kept alike.</span
        >
      {/if}
    </fieldset>
  {:else}
    <FieldRow label="Library" for={`${id}-library`}>
      <select id={`${id}-library`} value={editor.libraryId} disabled>
        <option value={editor.libraryId}
          >{libraries.find((library) => library.id === editor.libraryId)?.title ??
            editor.libraryId}</option
        >
      </select>
    </FieldRow>
  {/if}

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
      hint="A set is a group whose collections it creates; Split by names it. An existing group becomes this set."
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
        : "The collection inherits the group's defaults."}
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
  .libraries {
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

</style>
