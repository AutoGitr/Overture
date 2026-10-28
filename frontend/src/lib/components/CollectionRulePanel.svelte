<script lang="ts">
  import { CollectionEditor, type CollectionDraft } from "../utils/collectionForms.svelte";
  import { errorMessage } from "../utils/errors";
  import DetailForm from "./DetailForm.svelte";
  import PendingButton from "./PendingButton.svelte";
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
    {#if editor instanceof CollectionEditor && !editor.collection.managed}
      <p class="hint form-wide">
        Saving takes this collection over: Overture then keeps its members to these criteria.
      </p>
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
    <div class="form-wide preview">
      <PendingButton
        type="button"
        class="btn btn-secondary"
        pending={editor.preview.pending}
        pendingLabel="Previewing..."
        disabled={!editor.libraryId}
        onclick={() => editor.preview.run()}>Preview members</PendingButton
      >
      {#if editor.preview.error}
        <p role="alert">{errorMessage(editor.preview.error, "Could not preview the members")}</p>
      {:else if editor.preview.result}
        {@const result = editor.preview.result}
        <p class="hint">
          {result.member_count}
          {result.member_count === 1 ? "member" : "members"}{result.members.length
            ? `: ${result.members.join(", ")}${result.member_count > result.members.length ? ", ..." : ""}`
            : ""}
        </p>
        {@const recommendation = result.recommendation}
        {#if recommendation && (recommendation.kind === "smart") !== !!editor.rule.smart}
          <p class="hint" role="note">
            {recommendation.kind === "smart" ? "A smart collection" : "A regular collection"} suits these
            criteria: {recommendation.reason}.
            <button
              type="button"
              class="btn btn-ghost btn-sm"
              onclick={() => (editor.rule.smart = recommendation.kind === "smart")}>Switch</button
            >
          </p>
        {/if}
      {/if}
    </div>
  {/if}
</DetailForm>

<style>
  .preview {
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: var(--space-2);
  }

  .criteria {
    min-width: 0;
    margin: 0;
    padding: 0;
    border: 0;
  }
</style>
