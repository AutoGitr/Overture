<script lang="ts">
  import { createMutation, createQuery } from "@tanstack/svelte-query";
  import {
    createSavedFilterMutation,
    deleteSavedFilterMutation,
    getLibraryFilterCapabilitiesOptions,
    listSavedFiltersOptions,
    updateSavedFilterMutation,
  } from "../../generated/rest/@tanstack/svelte-query.gen";
  import type { FilterGroupInput, MediaType } from "../../generated/rest/types.gen";
  import { invalidateTags } from "../rest/cache";
  import { settingsState } from "../stores/settingsState.svelte";
  import { emptyGroup } from "../utils/collectionCriteria";
  import { errorMessage } from "../utils/errors";
  import CriteriaEditor from "./CriteriaEditor.svelte";
  import FieldRow from "./FieldRow.svelte";
  import PopupSection from "./PopupSection.svelte";

  let {
    filterId = $bindable(),
    mediaType,
    libraryId,
  }: {
    /** The saved filter the list applies, or null for none. */
    filterId: number | null;
    mediaType: MediaType;
    /** The library whose values conditions suggest. */
    libraryId: string;
  } = $props();

  interface Draft {
    /** The saved filter being edited; null for a new one. */
    id: number | null;
    name: string;
    criteria: FilterGroupInput;
  }

  let draft = $state<Draft | null>(null);
  const saved = createQuery(() => listSavedFiltersOptions());
  /** The saved filters every condition of which can test this media type's titles. */
  let offered = $derived(
    (saved.data ?? []).filter((entry) => entry.media_types.includes(mediaType)),
  );
  let elsewhere = $derived((saved.data?.length ?? 0) - offered.length);
  const capabilities = createQuery(() => ({
    ...getLibraryFilterCapabilitiesOptions({ query: { media_type: mediaType } }),
    enabled: draft !== null,
  }));
  const create = createMutation(() => createSavedFilterMutation());
  const update = createMutation(() => updateSavedFilterMutation());
  const remove = createMutation(() => deleteSavedFilterMutation());

  let failure = $state("");
  let busy = $derived(create.isPending || update.isPending || remove.isPending);
  let selected = $derived(offered.find((entry) => entry.id === filterId) ?? null);

  function edit(existing: boolean) {
    failure = "";
    draft =
      existing && selected
        ? { id: selected.id, name: selected.name, criteria: structuredClone(selected.criteria) }
        : { id: null, name: "", criteria: emptyGroup() };
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
      draft = null;
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
      draft = null;
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
      <select
        id="custom-filter"
        value={filterId ?? ""}
        onchange={(event) =>
          (filterId = event.currentTarget.value ? Number(event.currentTarget.value) : null)}
        disabled={busy}
      >
        <option value="">None</option>
        {#each offered as entry (entry.id)}
          <option value={entry.id}>{entry.name}</option>
        {/each}
      </select>
      <button type="button" class="btn btn-secondary btn-sm" onclick={() => edit(false)}>New</button>
      {#if selected}
        <button type="button" class="btn btn-secondary btn-sm" onclick={() => edit(true)}>Edit</button>
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
        <input id="custom-filter-name" bind:value={draft.name} maxlength="100" />
      </FieldRow>
      {#if capabilities.data}
        <CriteriaEditor
          bind:group={draft.criteria}
          fields={capabilities.data.fields}
          sources={capabilities.data.sources}
          {mediaType}
          {libraryId}
          scope={`${mediaType === "movie" ? "movies" : "shows"} on ${settingsState.media_server_name}`}
          label="Custom filter conditions"
        />
      {:else if capabilities.isError}
        <p class="hint">{errorMessage(capabilities.error, "Failed to load the filter fields")}</p>
      {/if}
      {#if failure}<p class="hint error" role="alert">{failure}</p>{/if}
      <div class="actions">
        <button type="button" class="btn btn-secondary btn-sm" onclick={() => (draft = null)}
          >Cancel</button
        >
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
          disabled={busy || !draft.name.trim()}>Save filter</button
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

  .pick select {
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
