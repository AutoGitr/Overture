<script lang="ts">
  import { TEXT_LIMITS } from "../../generated/settings";
  import type { LibrarySectionRead } from "../../generated/rest/types.gen";
  import type { CollectionGroupEditor } from "../utils/collectionGroupEditor.svelte";
  import DetailForm from "./DetailForm.svelte";
  import FieldRow from "./FieldRow.svelte";
  import LibraryOptions from "./LibraryOptions.svelte";
  import SetSetupFields from "./SetSetupFields.svelte";

  let {
    editor,
    libraries,
  }: {
    editor: CollectionGroupEditor;
    libraries: LibrarySectionRead[];
  } = $props();

  const id = $props.id();
  let form = $derived(editor.form);
  let renamed = $derived(editor.actions.name.trim());
</script>

<DetailForm
  collapsible
  expanded
  title="Setup"
  description={form.generator
    ? "One collection per value in its libraries, such as each decade, kept up to date."
    : "Its collections inherit its settings unless they set their own."}
  busy={editor.busy}
>
  <FieldRow label="Name" for={`${id}-name`}>
    <div class="rename">
      <input
        id={`${id}-name`}
        required
        maxlength={TEXT_LIMITS.groupName}
        bind:value={editor.actions.name}
      />
      <button
        type="button"
        class="btn btn-secondary"
        disabled={editor.busy || !renamed || renamed === editor.name}
        onclick={() => void editor.rename()}>Rename</button
      >
    </div>
  </FieldRow>
  {#if form.generator}
    {@const generator = form.generator}
    <SetSetupFields
      {generator}
      dimensions={form.dimensions}
      onchoose={(dimension) => form.chooseDimension(dimension)}
    />
    <fieldset class="libraries">
      <LibraryOptions
        {libraries}
        selected={generator.library_ids}
        ontoggle={(id) => form.setLibrary(id, !generator.library_ids.includes(id))}
        ontoggleall={(checked) => {
          for (const library of libraries) form.setLibrary(library.id, checked);
        }}
      />
    </fieldset>
  {/if}
</DetailForm>

<style>
  .rename {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
  }

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
