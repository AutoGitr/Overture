<script lang="ts">
  import { uiState } from "../stores/uiState.svelte";
  import DetailForm from "./DetailForm.svelte";
  import SegmentedControl from "./SegmentedControl.svelte";
  import { CollectionDraft, type CollectionEditor } from "../utils/collectionForms.svelte";
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
  let presets = $derived(draft?.presets.data ?? []);
  let preset = $derived(presets.find((entry) => entry.key === draft?.presetKey));
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
  <label class="form-label">
    Library
    <select
      required
      value={editor.libraryId}
      disabled={!draft}
      onchange={(event) => draft?.selectLibrary(event.currentTarget.value)}
    >
      <option value="">Select a library</option>
      {#if !draft && editor.libraryId && !libraries.some((library) => library.id === editor.libraryId)}
        <option value={editor.libraryId}>{editor.libraryId}</option>
      {/if}
      {#each libraries as library (library.id)}
        <option value={library.id}>{library.title}</option>
      {/each}
    </select>
  </label>

  {#if draft}
    {@const form = draft}
    <label class="form-label">
      Start from
      <select
        value={form.presetKey}
        onchange={(event) =>
          form.applyPreset(presets.find((entry) => entry.key === event.currentTarget.value))}
      >
        <option value="">Blank</option>
        <optgroup label="One collection">
          {#each presets.filter((entry) => entry.collection) as entry (entry.key)}
            <option value={entry.key}>{entry.label}</option>
          {/each}
        </optgroup>
        <optgroup label="One collection per value">
          {#each presets.filter((entry) => entry.set) as entry (entry.key)}
            <option value={entry.key}>{entry.label}</option>
          {/each}
        </optgroup>
      </select>
      <span class="hint"
        >{preset?.description ?? "A preset fills in the form, which stays editable."}</span
      >
    </label>
    <div class="form-label">
      <span>Create</span>
      <SegmentedControl
        --segmented-margin="0"
        label="Create"
        options={KINDS}
        bind:value={() => form.kind, (kind) => form.selectKind(kind)}
      />
    </div>
  {/if}

  {#if creatingSet}
    <label class="form-label">
      Group
      <input
        maxlength="200"
        bind:value={editor.collectionGroup}
        placeholder={draft?.setGroup || "e.g. Decades"}
        list={`${id}-groups`}
      />
      <datalist id={`${id}-groups`}>
        {#each groups as group (group)}<option value={group}></option>{/each}
      </datalist>
      <span class="hint"
        >The set's collections share this group and its defaults. Blank names it after the values.</span
      >
    </label>
  {:else}
    <label class="form-label">
      Title
      <input
        required
        maxlength="200"
        bind:value={editor.title}
        disabled={editor.generated}
        placeholder="Collection title"
      />
    </label>

    <div class="form-label">
      <label for={`${id}-group`}>Group</label>
      <select
        id={`${id}-group`}
        disabled={editor.generated}
        value={editor.collectionGroup}
        onchange={(event) => {
          if (event.currentTarget.value !== NEW_GROUP) {
            editor.collectionGroup = event.currentTarget.value;
            return;
          }
          // The select keeps showing the current group until the popup creates one.
          event.currentTarget.value = editor.collectionGroup;
          uiState.openCollectionGroups("", (name, replacement) => {
            if (!name || editor.collectionGroup === name) editor.collectionGroup = replacement;
          });
        }}
      >
        <option value="">No group</option>
        {#if editor.collectionGroup && !groups.includes(editor.collectionGroup)}
          <option value={editor.collectionGroup}>{editor.collectionGroup}</option>
        {/if}
        {#each groups as group (group)}<option value={group}>{group}</option>{/each}
        <option value={NEW_GROUP}>Create new group...</option>
      </select>
      <span class="hint"
        >{editor.generated
          ? "Its group's set titles this collection."
          : "The collection inherits the group's defaults."}</span
      >
    </div>
  {/if}
</DetailForm>
