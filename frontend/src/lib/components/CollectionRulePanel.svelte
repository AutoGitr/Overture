<script lang="ts">
  import { CollectionEditor, type CollectionDraft } from "../utils/collectionForms.svelte";
  import DetailForm from "./DetailForm.svelte";
  import CriteriaEditor from "./CriteriaEditor.svelte";
  import SegmentedControl from "./SegmentedControl.svelte";

  let { editor }: { editor: CollectionEditor | CollectionDraft } = $props();

  const CONTENT = [
    ["manual", "Manual"],
    ["criteria", "Criteria"],
  ] as const;
  const EVALUATION = [
    ["overture", "Overture"],
    ["smart", "Plex (smart)"],
  ] as const;
  let capabilities = $derived(editor.capabilities.data);
  let editable = $derived(!editor.generated && editor.criteriaEditable);
</script>

<DetailForm
  collapsible
  expanded
  title="Content"
  description={editor.generated
    ? "Its group's set decides the criteria."
    : editor.content === "manual"
      ? "Choose members by hand in Members."
      : editor.smart
        ? "Plex keeps the members current, with play state per user."
        : "Each sync adds what matches the criteria."}
  busy={editor.busy}
>
  {#if editor instanceof CollectionEditor && !editor.generated}
    {@const form = editor}
    <div class="form-label">
      <span>Members</span>
      <SegmentedControl
        --segmented-margin="0"
        label="Members"
        options={CONTENT}
        bind:value={form.content}
      />
    </div>
  {/if}
  {#if editor.content === "criteria"}
    {#if capabilities?.smart}
      <div class="form-label">
        <span>Evaluated by</span>
        <SegmentedControl
          --segmented-margin="0"
          label="Evaluated by"
          options={EVALUATION}
          bind:value={
            () => (editor.rule.smart ? "smart" : "overture"),
            (value) => (editor.rule.smart = value === "smart")
          }
        />
        <span class="hint"
          >{editor.rule.smart
            ? "Live, per user and with every Plex filter. Lists and tags become Plex labels."
            : "Uses library metadata, so play state is as of the last library sync."}</span
        >
      </div>
    {/if}
    {#if editor instanceof CollectionEditor && !editor.criteriaEditable}
      {@const form = editor}
      <div class="form-wide">
        <p class="hint">
          Plex holds this smart collection's filter. Replace it to edit the criteria here.
        </p>
        <label class="form-row">
          <input type="checkbox" bind:checked={form.manageServerFilter} />
          Replace the Plex filter with these criteria
        </label>
      </div>
    {/if}
    <fieldset class="criteria form-wide" disabled={!editable}>
      <legend class="sr-only">Criteria</legend>
      <CriteriaEditor
        group={editor.rule.criteria}
        fields={editor.fields}
        sources={capabilities?.sources ?? []}
        mediaType={editor.mediaType}
        libraryId={editor.libraryId}
        label="Criteria"
      />
    </fieldset>
  {/if}
</DetailForm>

<style>
  .criteria {
    min-width: 0;
    margin: 0;
    padding: 0;
    border: 0;
  }
</style>
