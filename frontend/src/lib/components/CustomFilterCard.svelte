<script lang="ts">
  import { TEXT_LIMITS } from "../../generated/settings";
  import { createMutation, createQuery } from "@tanstack/svelte-query";
  import { untrack } from "svelte";
  import {
    createSavedFilterMutation,
    deleteSavedFilterMutation,
    getLibraryFilterCapabilitiesOptions,
    listSavedFiltersOptions,
    updateSavedFilterMutation,
  } from "../../generated/rest/@tanstack/svelte-query.gen";
  import type {
    FilterGroupOutput,
    MediaType,
    SavedFilterRead,
  } from "../../generated/rest/types.gen";
  import { invalidateTags } from "../rest/cache";
  import { settingsState } from "../stores/settingsState.svelte";
  import { emptyGroup } from "../utils/collectionCriteria";
  import { errorMessage } from "../utils/errors";
  import CriteriaEditor from "./CriteriaEditor.svelte";
  import FieldRow from "./FieldRow.svelte";
  import PopupSection from "./PopupSection.svelte";
  import Select from "./Select.svelte";
  import type { SelectOption } from "../utils/selectOptions";

  let {
    filterId = $bindable(),
    mediaType,
  }: {
    /** The saved filter the list applies, or null for none. */
    filterId: number | null;
    mediaType: MediaType;
  } = $props();

  interface Draft {
    /** The saved filter being edited; null for a new one. */
    id: number | null;
    name: string;
    criteria: FilterGroupOutput;
  }

  const saved = createQuery(() => listSavedFiltersOptions());
  /** The saved filters every condition of which can test this media type's titles. */
  let offered = $derived(
    (saved.data ?? []).filter((entry) => entry.media_types.includes(mediaType)),
  );
  let filterOptions = $derived<SelectOption<number | null>[]>([
    { value: null, label: "None" },
    ...offered.map((entry) => ({ value: entry.id, label: entry.name })),
  ]);
  let elsewhere = $derived((saved.data?.length ?? 0) - offered.length);
  let selected = $derived(offered.find((entry) => entry.id === filterId) ?? null);
  /** The chosen filter's ID: the draft starts over only when another is chosen. */
  let selectedId = $derived(selected?.id ?? null);

  /** An editable, deeply reactive draft. */
  function editable(value: Draft): Draft {
    const copy = $state(value);
    return copy;
  }

  function copyOf(entry: SavedFilterRead | null): Draft | null {
    return entry
      ? editable({ id: entry.id, name: entry.name, criteria: structuredClone(entry.criteria) })
      : null;
  }

  /**
   * The chosen filter, ready to change; a refetch of the saved filters keeps
   * the edits, as only choosing another filter starts it over.
   */
  let draft = $derived.by(() => {
    void selectedId;
    return untrack(() => copyOf(selected));
  });
  /** It differs from the chosen filter, or is a new one. */
  let changed = $derived(
    draft !== null &&
      (draft.id === null ||
        draft.name !== selected?.name ||
        JSON.stringify(draft.criteria) !== JSON.stringify(selected.criteria)),
  );
  const capabilities = createQuery(() => ({
    ...getLibraryFilterCapabilitiesOptions({ query: { media_type: mediaType } }),
    enabled: draft !== null,
  }));
  const create = createMutation(() => createSavedFilterMutation());
  const update = createMutation(() => updateSavedFilterMutation());
  const remove = createMutation(() => deleteSavedFilterMutation());

  let failure = $state("");
  let busy = $derived(create.isPending || update.isPending || remove.isPending);

  function startNew() {
    failure = "";
    draft = editable({ id: null, name: "", criteria: emptyGroup() });
  }

  /** Leave a new filter, or the changes to the chosen one. */
  function discard() {
    failure = "";
    draft = copyOf(selected);
  }

  async function save(asNew: boolean) {
    if (!draft) return;
    const body = { name: draft.name, media_type: mediaType, criteria: draft.criteria };
    try {
      const stored =
        draft.id === null || asNew
          ? await create.mutateAsync({ body })
          : await update.mutateAsync({ body, path: { filter_id: draft.id } });
      await invalidateTags(["library-filters"]);
      filterId = stored.id;
      // The same filter saved keeps its ID, so the draft is taken anew.
      draft = copyOf(stored);
    } catch (error) {
      failure = errorMessage(error, "The filter could not be saved");
    }
  }

  async function forget() {
    if (!selected) return;
    try {
      await remove.mutateAsync({ path: { filter_id: selected.id } });
      await invalidateTags(["library-filters"]);
      filterId = null;
    } catch (error) {
      failure = errorMessage(error, "The filter could not be deleted");
    }
  }
</script>

<PopupSection
  label="Custom filter"
  description="Test any metadata, list or status, with conditions matched together or apart."
>
  <FieldRow label="Saved filter" for="custom-filter">
    <div class="pick">
      <Select
        id="custom-filter"
        disabled={busy}
        options={filterOptions}
        bind:value={filterId}
      />
      <button type="button" class="btn btn-secondary btn-sm" onclick={startNew}>New</button>
      {#if selected}
        <button type="button" class="btn btn-secondary btn-sm" onclick={forget} disabled={busy}
          >Delete</button
        >
      {/if}
    </div>
  </FieldRow>
  {#if elsewhere}
    <p class="hint">
      {elsewhere === 1 ? "One saved filter tests" : `${elsewhere} saved filters test`} what
      {mediaType === "movie" ? "movies" : "shows"} lack, so the {mediaType === "movie"
        ? "Shows"
        : "Movies"} tab offers {elsewhere === 1 ? "it" : "them"}.
    </p>
  {/if}

  {#if draft}
    <div class="editor">
      <FieldRow label="Name" for="custom-filter-name">
        <input id="custom-filter-name" bind:value={draft.name} maxlength={TEXT_LIMITS.displayName} />
      </FieldRow>
      {#if capabilities.data}
        <CriteriaEditor
          bind:group={draft.criteria}
          fields={capabilities.data.fields}
          sources={capabilities.data.sources}
          {mediaType}
          libraryId={null}
          scope={`${mediaType === "movie" ? "movies" : "shows"} on ${settingsState.media_server_name}`}
          label="Custom filter conditions"
        />
      {:else if capabilities.isError}
        <p class="hint">{errorMessage(capabilities.error, "Failed to load the filter fields")}</p>
      {/if}
      {#if failure}<p class="hint error" role="alert">{failure}</p>{/if}
      <div class="actions">
        {#if changed}
          <button type="button" class="btn btn-secondary btn-sm" onclick={discard}
            >{draft.id === null ? "Cancel" : "Discard changes"}</button
          >
        {/if}
        {#if draft.id !== null}
          <button
            type="button"
            class="btn btn-secondary btn-sm"
            onclick={() => save(true)}
            disabled={busy || !draft.name.trim()}>Save as new</button
          >
        {/if}
        <button
          type="button"
          class="btn btn-primary btn-sm"
          onclick={() => save(false)}
          disabled={busy || !changed || !draft.name.trim()}>Save filter</button
        >
      </div>
    </div>
  {/if}
</PopupSection>

<style>
  .pick {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
    align-items: center;
  }

  .pick :global(.combobox) {
    flex: 1 1 10rem;
    min-width: 0;
  }

  .editor {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }

  .actions {
    display: flex;
    flex-wrap: wrap;
    justify-content: flex-end;
    gap: var(--space-2);
  }

  .error {
    color: var(--danger);
  }
</style>
