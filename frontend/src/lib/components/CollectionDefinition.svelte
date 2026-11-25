<script lang="ts">
  import { TEXT_LIMITS, UNGROUPED_GROUP } from "../../generated/settings";

  import { uiState } from "../stores/uiState.svelte";
  import DetailForm from "./DetailForm.svelte";
  import FieldRow from "./FieldRow.svelte";
  import SegmentedControl from "./SegmentedControl.svelte";
  import { CollectionDraft } from "../utils/collectionDraft.svelte";
  import type { CollectionEditor } from "../utils/collectionEditor.svelte";
  import Notice from "./Notice.svelte";
  import SetDimensionField from "./SetDimensionField.svelte";
  import type { LibrarySectionRead } from "../../generated/rest/types.gen";
  import LibraryOptions from "./LibraryOptions.svelte";
  import CollectionPresetField from "./CollectionPresetField.svelte";
  import Select from "./Select.svelte";
  import { toOptions } from "../utils/selectOptions";
  import { NEW_GROUP_OPTION, groupOptions } from "../utils/collectionGroups.svelte";
  import ValueCombobox from "./ValueCombobox.svelte";

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
  const KINDS = [
    ["collection", "One collection"],
    ["set", "One per value"],
  ] as const;
  let draft = $derived(editor instanceof CollectionDraft ? editor : null);
  let creatingSet = $derived(draft?.kind === "set");
  let groupChoices = $derived([...groupOptions(groups, editor.collectionGroup), NEW_GROUP_OPTION]);
  /** Choosing to create a group keeps the current one until Collection groups makes it. */
  function chooseGroup(chosen: string) {
    if (chosen !== NEW_GROUP_OPTION.value) {
      editor.collectionGroup = chosen;
      return;
    }
    uiState.openCollectionGroups("", (name, replacement) => {
      if (!name || editor.collectionGroup === name) editor.collectionGroup = replacement;
    });
  }
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
    <CollectionPresetField draft={form} />
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
    <LibraryOptions
      {libraries}
      selected={editor.libraryIds}
      ontoggle={(id) => editor.setLibrary(id, !editor.libraryIds.includes(id))}
      ontoggleall={(checked) => {
        for (const library of libraries) {
          if (editor.libraryIds.includes(library.id) !== checked) {
            editor.setLibrary(library.id, checked);
          }
        }
      }}
    />
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
        maxlength={TEXT_LIMITS.setTitleFormat}
        bind:value={form.generator.title_format}
        placeholder={"{value}"}
      />
    </FieldRow>
    <FieldRow
      label="Group"
      for={`${id}-group`}
      hint="A set is a group whose collections it creates; Split by names it. A group that holds collections can become a set; one that already is a set cannot."
    >
      <ValueCombobox
        id={`${id}-group`}
        required={false}
        maxlength={TEXT_LIMITS.groupName}
        placeholder="e.g. Decades"
        bind:value={form.collectionGroup}
        options={toOptions(groups)}
      />
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
        maxlength={TEXT_LIMITS.collectionTitle}
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
      <Select
        id={`${id}-group`}
        disabled={editor.generated}
        options={groupChoices}
        bind:value={() => editor.collectionGroup || UNGROUPED_GROUP, chooseGroup}
      />
    </FieldRow>
  {/if}

</DetailForm>

<style>
  .libraries {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    min-width: 0;
    margin: 0;
    padding: 0;
    border: 0;
  }
</style>
