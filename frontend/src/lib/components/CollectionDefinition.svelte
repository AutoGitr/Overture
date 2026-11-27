<script lang="ts">
  import { TEXT_LIMITS } from "../../generated/settings";
  import type { LibrarySectionRead } from "../../generated/rest/types.gen";
  import { goToGroup } from "../router/routes";
  import { CollectionDraft } from "../utils/collectionDraft.svelte";
  import type { CollectionEditor } from "../utils/collectionEditor.svelte";
  import { groupOptions } from "../utils/collectionGroups.svelte";
  import CollectionPresetField from "./CollectionPresetField.svelte";
  import DetailForm from "./DetailForm.svelte";
  import FieldRow from "./FieldRow.svelte";
  import LibraryOptions from "./LibraryOptions.svelte";
  import Notice from "./Notice.svelte";
  import SegmentedControl from "./SegmentedControl.svelte";
  import SetSetupFields from "./SetSetupFields.svelte";
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
  /** The groups it can join; typing another name makes a group of it once saved. */
  let groupChoices = $derived(groupOptions(groups, editor.collectionGroup));
</script>

<DetailForm
  collapsible
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
    {#if creatingSet && form.set.generator}
      <SetSetupFields
        generator={form.set.generator}
        dimensions={form.set.dimensions}
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

  {#if !creatingSet}
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
  {/if}
  <FieldRow
    label="Group"
    for={`${id}-group`}
    hint={creatingSet
      ? "A set is a group whose collections it creates; Split by names it. A group that holds collections can become a set; one that already is a set cannot."
      : editor.generated
        ? "Its group's set titles this collection."
        : (draft?.groupHint ??
          "Every collection belongs to a group, whose defaults it inherits; a new name makes a group of it.")}
  >
    <fieldset class="group" disabled={editor.generated}>
      <ValueCombobox
        id={`${id}-group`}
        maxlength={TEXT_LIMITS.groupName}
        placeholder={creatingSet ? "e.g. Decades" : "e.g. Franchises"}
        bind:value={editor.collectionGroup}
        options={groupChoices}
      />
    </fieldset>
  </FieldRow>
  {#each draft && creatingSet ? draft.setNotices : [] as notice (notice.title)}
    <Notice
      tone={notice.tone}
      title={notice.title}
      message={notice.message}
      action={notice.group
        ? { label: "Open group", run: () => goToGroup(notice.group ?? "") }
        : undefined}
    />
  {/each}
</DetailForm>

<style>
  .libraries,
  .group {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    min-width: 0;
    margin: 0;
    padding: 0;
    border: 0;
  }
</style>
