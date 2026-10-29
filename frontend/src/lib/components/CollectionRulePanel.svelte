<script lang="ts">
  import type { CollectionDraft, CollectionEditor } from "../utils/collectionForms.svelte";
  import { errorMessage } from "../utils/errors";
  import DetailForm from "./DetailForm.svelte";
  import FieldRow from "./FieldRow.svelte";
  import PendingButton from "./PendingButton.svelte";
  import CriteriaEditor from "./CriteriaEditor.svelte";
  import SegmentedControl from "./SegmentedControl.svelte";

  let { editor }: { editor: CollectionEditor | CollectionDraft } = $props();

  const EVALUATION = [
    ["overture", "Overture"],
    ["smart", "Plex (smart)"],
  ] as const;
  let capabilities = $derived(editor.capabilities.data);

</script>

<DetailForm
  collapsible
  expanded
  title="Content"
  description={editor.generated
    ? "Its group's set decides the criteria."
    : editor.smart
      ? "Plex keeps the members current, with play state per user."
      : "Each sync adds what matches the criteria."}
  busy={editor.busy}
  disabled={!editor.libraryId}
>
  {#if capabilities?.smart}
      <FieldRow
        label="Evaluated by"
        hint={editor.rule.smart
          ? "Live, per user and with every Plex filter. Lists and tags become Plex labels."
          : "Uses library metadata, so play state is as of the last library sync."}
      >
        <SegmentedControl
          label="Evaluated by"
          options={EVALUATION}
          bind:value={
            () => (editor.rule.smart ? "smart" : "overture"),
            (value) => (editor.rule.smart = value === "smart")
          }
        />
      </FieldRow>
    {/if}
    <fieldset class="criteria" disabled={editor.generated}>
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
    <div class="preview">
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
