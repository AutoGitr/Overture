<script lang="ts">
  import { settingsState } from "../stores/settingsState.svelte";
  import { uiState } from "../stores/uiState.svelte";
  import DetailForm from "./DetailForm.svelte";
  import FieldRow from "./FieldRow.svelte";
  import SegmentedControl from "./SegmentedControl.svelte";
  import {
    CollectionDraft,
    PresetActions,
    type CollectionEditor,
  } from "../utils/collectionForms.svelte";
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
  const presetActions = new PresetActions(() => editor);
  let draft = $derived(editor instanceof CollectionDraft ? editor : null);
  let creatingSet = $derived(draft?.kind === "set");
  let presets = $derived(draft?.presets.data ?? []);
  let preset = $derived(presets.find((entry) => entry.key === draft?.presetKey));
  let saved = $derived(presets.filter((entry) => entry.saved_id != null));
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

    <FieldRow
      label="Start from"
      for={`${id}-start`}
      hint={preset?.description || "A preset fills in the form, which stays editable."}
    >
      <select
        id={`${id}-start`}
        value={form.presetKey}
        onchange={(event) =>
          form.applyPreset(presets.find((entry) => entry.key === event.currentTarget.value))}
      >
        <option value="">Blank</option>
        {#if saved.length}
          <optgroup label="Saved">
            {#each saved as entry (entry.key)}
              <option value={entry.key}>{entry.label}</option>
            {/each}
          </optgroup>
        {/if}
        <optgroup label="One collection">
          {#each presets.filter((entry) => entry.collection && entry.saved_id == null) as entry (entry.key)}
            <option value={entry.key}>{entry.label}</option>
          {/each}
        </optgroup>
        <optgroup label="One collection per value">
          {#each presets.filter((entry) => entry.set && entry.saved_id == null) as entry (entry.key)}
            <option value={entry.key}>{entry.label}</option>
          {/each}
        </optgroup>
      </select>
    </FieldRow>
    {#if preset?.saved_id != null}
      {@const chosen = preset}
      <button
        type="button"
        class="btn btn-ghost btn-sm"
        disabled={presetActions.busy}
        onclick={async () => {
          await presetActions.delete(chosen);
          form.applyPreset(undefined);
        }}>Delete preset</button
      >
    {/if}
    <FieldRow label="Create">
      <SegmentedControl
        label="Create"
        options={KINDS}
        bind:value={() => form.kind, (kind) => form.selectKind(kind)}
      />
    </FieldRow>
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
    <label class="form-label">
      Title template
      <input
        required
        maxlength="200"
        bind:value={form.generator.title_format}
        placeholder={"{value}"}
      />
      <span class="hint">&#123;value&#125; becomes each value, such as 1990 or Action.</span>
    </label>
    <label class="form-label">
      Group
      <input
        maxlength="200"
        bind:value={form.collectionGroup}
        placeholder={form.setGroup || "e.g. Decades"}
        list={`${id}-groups`}
      />
      <datalist id={`${id}-groups`}>
        {#each groups as group (group)}<option value={group}></option>{/each}
      </datalist>
      <span class="hint"
        >A set is a group whose collections it creates. Blank names it after the values; an existing
        group becomes this set.</span
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
        {#if settingsState.current.collection_require_group}
          <option value="" disabled>Choose a group</option>
        {:else}
          <option value="">No group</option>
        {/if}
        {#if editor.collectionGroup && !groups.includes(editor.collectionGroup)}
          <option value={editor.collectionGroup}>{editor.collectionGroup}</option>
        {/if}
        {#each groups as group (group)}<option value={group}>{group}</option>{/each}
        <option value={NEW_GROUP}>Create new group...</option>
      </select>
    </FieldRow>
  {/if}

  <div class="form-label">
    <label for={`${id}-preset`}>Save as preset</label>
    <div class="preset-row">
      <input
        id={`${id}-preset`}
        maxlength="100"
        placeholder="Preset name"
        bind:value={presetActions.label}
        onkeydown={(event) => {
          // Enter saves the preset here, not the collection.
          if (event.key !== "Enter") return;
          event.preventDefault();
          void presetActions.save();
        }}
      />
      <button
        type="button"
        class="btn btn-secondary"
        disabled={presetActions.busy || !presetActions.label.trim()}
        onclick={() => void presetActions.save()}>Save preset</button
      >
    </div>
    <span class="hint">New collections can start from it under Start from.</span>
  </div>
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

  .preset-row {
    display: flex;
    gap: var(--space-2);
  }

  .preset-row input {
    flex: 1;
    min-width: 0;
  }
</style>
