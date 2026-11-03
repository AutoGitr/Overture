<script lang="ts">
  import { countOf } from "../utils/plural";
  import {
    switchKind,
    type CollectionDraft,
    type CollectionEditor,
  } from "../utils/collectionForms.svelte";
  import { errorMessage } from "../utils/errors";
  import DetailForm from "./DetailForm.svelte";
  import FieldRow from "./FieldRow.svelte";
  import Notice from "./Notice.svelte";
  import PendingButton from "./PendingButton.svelte";
  import SegmentedControl from "./SegmentedControl.svelte";
  import CriteriaEditor from "./CriteriaEditor.svelte";

  let { editor }: { editor: CollectionEditor | CollectionDraft } = $props();

  const KINDS = [
    ["regular", "Regular"],
    ["smart", "Smart"],
  ] as const;
  let capabilities = $derived(editor.capabilities.data);
  let recommendation = $derived(editor.preview.result?.recommendation ?? null);
  /** A kind the criteria need that the collection is not, which the preview found. */
  let suggested = $derived(
    recommendation && (recommendation.kind === "smart") !== !!editor.rule.smart
      ? recommendation
      : null,
  );
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
      label="Collection type"
      hint={editor.rule.smart
        ? "Plex evaluates it live, per user, with every Plex filter. Conditions Plex has no filter for, such as lists and tags, label the items they match so Plex can filter on the labels."
        : "Overture evaluates it on each sync from the library metadata, TMDB facts and lists it stored, so play state is as of the last library sync."}
    >
      <SegmentedControl
        label="Collection type"
        options={KINDS}
        bind:value={
          () => (editor.rule.smart ? "smart" : "regular"),
          (kind) => {
            if (!editor.generated) switchKind(editor, kind === "smart");
          }
        }
      />
    </FieldRow>
    {#if suggested}
      {@const smart = suggested.kind === "smart"}
      <Notice
        tone="info"
        title={smart ? "A smart collection suits these criteria" : "A regular collection suits these criteria"}
        message={`It is needed because ${suggested.reason}.`}
        action={{
          label: smart ? "Switch to smart" : "Switch to regular",
          run: () => switchKind(editor, smart),
        }}
      />
    {/if}
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
          {countOf(result.member_count, "member")}{result.members.length
            ? `: ${result.members.join(", ")}${result.member_count > result.members.length ? ", ..." : ""}`
            : ""}
        </p>
        {#if result.tmdb_unread}
          {@const one = result.tmdb_unread === 1}
          <p class="hint" role="note">
            {`${countOf(result.tmdb_unread, "title")} in this library ${one ? "has" : "have"} no TMDB facts yet. The next Full Sync reads them; until then, TMDB conditions cannot match ${one ? "it" : "them"}.`}
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
