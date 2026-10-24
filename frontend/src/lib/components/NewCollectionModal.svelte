<script lang="ts">
  import { createQuery } from "@tanstack/svelte-query";
  import {
    getLibrariesOptions,
    listItemsOptions,
  } from "../../generated/rest/@tanstack/svelte-query.gen";
  import { uiState } from "../stores/uiState.svelte";
  import { CollectionCreation } from "../utils/collectionForms.svelte";
  import DataStatus from "./DataStatus.svelte";
  import PopupShell from "./PopupShell.svelte";

  const form = new CollectionCreation(uiState.sidebarTab);

  const libraries = createQuery(() =>
    getLibrariesOptions({ query: { media_type: form.mediaType } }),
  );
  const items = createQuery(() => listItemsOptions({ query: { media_type: form.mediaType } }));

  let available = $derived.by(() => {
    if (!form.libraryId || !items.data?.items) return [];
    const query = form.search.trim().toLowerCase();

    return items.data.items.filter(
      (item) =>
        item.library_id === form.libraryId &&
        item.server_item_id &&
        !item.server_removed_at &&
        (form.memberIds.has(item.id) || !query || item.title.toLowerCase().includes(query)),
    );
  });

  let canSubmit = $derived(Boolean(form.title.trim() && form.libraryId && form.memberIds.size > 0));
  async function createCollection() {
    if (await form.create()) uiState.closePopup();
  }
</script>

<PopupShell title="Create collection" onclose={() => uiState.closePopup()}>
  <form
    class="options-col"
    onsubmit={(event) => {
      event.preventDefault();
      void createCollection();
    }}
  >
    <DataStatus
      label="libraries"
      error={libraries.error}
      loading={libraries.isFetching}
      hasData={libraries.data !== undefined}
      onretry={() => libraries.refetch()}
    />
    <DataStatus
      label="library items"
      error={items.error}
      loading={items.isFetching}
      hasData={items.data !== undefined}
      onretry={() => items.refetch()}
    />
    {#if form.createRequest.error}
      <DataStatus
        label="collection creation"
        error={form.createRequest.error}
        loading={false}
        hasData={false}
        onretry={createCollection}
      />
    {/if}

    <fieldset class="options-col" disabled={form.createRequest.isPending}>
      <legend>New collection</legend>

      <label class="form-label">
        Title
        <input required maxlength="200" bind:value={form.title} />
      </label>

      <label class="form-label">
        Library
        <select required bind:value={form.libraryId} onchange={() => form.memberIds.clear()}>
          <option value="">Select a library</option>
          {#each libraries.data ?? [] as library (library.id)}
            <option value={library.id}>{library.title}</option>
          {/each}
        </select>
      </label>

      <label class="form-label">
        Search members
        <input type="search" bind:value={form.search} disabled={!form.libraryId} />
      </label>

      <div class="member-choices" role="group" aria-label="Initial members">
        {#if !form.libraryId}
          <p class="text-muted">Select a library to view available items.</p>
        {:else if available.length === 0}
          <p class="text-muted">No matching items found.</p>
        {:else}
          {#each available as item (item.id)}
            <label class="form-row">
              <input
                type="checkbox"
                checked={form.memberIds.has(item.id)}
                onchange={() => form.toggle(item.id)}
              />
              {item.title}
              {item.year ? `(${item.year})` : ""}
            </label>
          {/each}
        {/if}
      </div>

      <button class="btn btn-primary" type="submit" disabled={!canSubmit}>
        Create collection ({form.memberIds.size} members)
      </button>
    </fieldset>
  </form>
</PopupShell>

<style>
  .member-choices {
    max-height: 40vh;
    overflow: auto;
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
</style>
