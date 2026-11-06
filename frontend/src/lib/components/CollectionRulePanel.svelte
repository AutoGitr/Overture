<script lang="ts">
  import type { LibrarySectionRead } from "../../generated/rest/types.gen";
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

  let {
    editor,
    libraries,
  }: { editor: CollectionEditor | CollectionDraft; libraries: LibrarySectionRead[] } = $props();

  const KINDS = [
    ["regular", "Regular"],
    ["smart", "Smart"],
  ] as const;
  let capabilities = $derived(editor.capabilities.data);
  // The editor owns its rule, so its criteria are bound here rather than through `editor`.
  let rule = $derived(editor.rule);

  function libraryName(id: string) {
    return libraries.find((library) => library.id === id)?.title ?? id;
  }
  let recommendation = $derived(editor.preview.recommendation);
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
  disabled={!editor.libraryIds.length}
>
  {#if capabilities?.smart}
    <FieldRow
      label="Collection type"
      hint={editor.rule.smart
        ? "Plex evaluates it live, per user, with every Plex filter. Conditions Plex has no filter for, such as lists, tags and TMDB facts, label the items they match so Plex can filter on the labels; Overture refreshes those labels on each sync."
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
        message={suggested.reason}
        action={{
          label: smart ? "Switch to smart" : "Switch to regular",
          run: () => switchKind(editor, smart),
        }}
      />
    {/if}
  {/if}
  {#if !rule.libraries.length}
    <p class="hint">Choose a library in Setup, then what the collection holds from it.</p>
  {/if}
  {#each rule.libraries as entry (entry.library_id)}
    {@const mediaType = editor.typeOf(entry.library_id)}
    {@const result = editor.preview.resultFor(entry.library_id)}
    {@const name = libraryName(entry.library_id)}
    <fieldset class="criteria" disabled={editor.generated}>
      <legend class="form-label">{name}</legend>
      <CriteriaEditor
        bind:group={entry.criteria}
        fields={editor.fieldsFor(mediaType)}
        sources={editor.options.for(mediaType).data?.sources ?? []}
        {mediaType}
        libraryId={entry.library_id}
        label={rule.libraries.length > 1 ? `${name} criteria` : "Criteria"}
      />
      {#if result}
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
    </fieldset>
  {/each}
  <div class="preview">
    <div class="actions-row">
      <PendingButton
        type="button"
        class="btn btn-secondary"
        pending={editor.preview.pending}
        pendingLabel="Previewing..."
        disabled={!editor.libraryIds.length}
        onclick={() => editor.preview.run()}>Preview members</PendingButton
      >
    </div>
    {#if editor.preview.error}
      <p role="alert">{errorMessage(editor.preview.error, "Could not preview the members")}</p>
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
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    min-width: 0;
    margin: 0;
    padding: var(--space-3);
    border: var(--border-subtle);
    border-radius: var(--radius-md);
  }

  .criteria legend {
    padding: 0 var(--space-1);
  }
</style>
