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
    ? "Creates one collection per value in the library, such as each decade, and keeps them up to date."
    : "Choose where the collection lives, then give it a name and an optional group."}
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
        >{preset?.description ?? "Presets fill in everything below, which stays editable."}</span
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
        >The collections share this group and its defaults, such as sort titles and visibility.
        Blank names it after what it splits by.</span
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
      {#if editor.generated}<span class="hint"
          >The collection set of its group titles this collection.</span
        >{/if}
    </label>

    <div class="form-label">
      <label for={`${id}-group`}>Group</label>
      <select
        id={`${id}-group`}
        disabled={editor.generated}
        value={groups.includes(editor.collectionGroup)
          ? editor.collectionGroup
          : editor.collectionGroup
            ? "__new__"
            : ""}
        onchange={(event) => {
          editor.collectionGroup =
            event.currentTarget.value === "__new__" ? "New group" : event.currentTarget.value;
        }}
      >
        <option value="">No group</option>
        {#each groups as group (group)}<option value={group}>{group}</option>{/each}
        <option value="__new__">Create new group...</option>
      </select>
      {#if editor.collectionGroup && !groups.includes(editor.collectionGroup)}
        <label for={`${id}-new-group`}>New group name</label>
        <input
          id={`${id}-new-group`}
          required
          maxlength="200"
          bind:value={editor.collectionGroup}
        />
      {/if}
      <span class="hint">Group defaults apply unless this collection overrides them.</span>
      <button
        type="button"
        class="btn btn-ghost btn-sm"
        onclick={() =>
          uiState.openCollectionGroups(editor.collectionGroup, (name, replacement) => {
            if (editor.collectionGroup === name) editor.collectionGroup = replacement;
          })}>{editor.generated ? "Edit the set" : "Manage groups"}</button
      >
    </div>
  {/if}
</DetailForm>
