<script lang="ts">
  import { createQuery } from "@tanstack/svelte-query";
  import {
    getLibrariesOptions,
    listItemsOptions,
  } from "../../generated/rest/@tanstack/svelte-query.gen";
  import { CollectionCreation } from "../utils/collectionForms.svelte";
  import { uiState } from "../stores/uiState.svelte";
  import DataStatus from "./DataStatus.svelte";
  import PopupShell from "./PopupShell.svelte";
  const form = new CollectionCreation(uiState.sidebarTab);
  const libraries = createQuery(() =>
    getLibrariesOptions({ query: { media_type: form.mediaType } }),
  );
  const items = createQuery(() => listItemsOptions({ query: { media_type: form.mediaType } }));
  let available = $derived(
    (items.data?.items ?? []).filter(
      (item) =>
        item.library_id === form.libraryId &&
        item.server_item_id &&
        !item.server_removed_at &&
        (form.memberIds.includes(item.id) ||
          item.title.toLowerCase().includes(form.search.toLowerCase())),
    ),
  );
</script>

<PopupShell title="Create collection" onclose={() => uiState.closePopup()}>
  <form
    class="options-col"
    onsubmit={async (event) => {
      event.preventDefault();
      if (await form.create()) uiState.closePopup();
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
    <fieldset class="options-col" disabled={form.createRequest.isPending}>
      <legend>New collection</legend>
      <label class="form-label"
        >Title<input required maxlength="200" bind:value={form.title} /></label
      >
      <label class="form-label"
        >Library<select required bind:value={form.libraryId} onchange={() => (form.memberIds = [])}
          ><option value="">Select a library</option
          >{#each libraries.data ?? [] as library (library.id)}<option value={library.id}
              >{library.title}</option
            >{/each}</select
        ></label
      >
      <label class="form-label"
        >Search members<input type="search" bind:value={form.search} /></label
      >
      <div class="member-choices" aria-label="Initial members">
        {#each available as item (item.id)}<label class="form-row"
            ><input
              type="checkbox"
              checked={form.memberIds.includes(item.id)}
              onchange={() => form.toggle(item.id)}
            />{item.title}
            {item.year ? `(${item.year})` : ""}</label
          >{/each}
      </div>
      <button
        class="btn btn-primary"
        type="submit"
        disabled={!form.memberIds.length || !form.libraryId}
        >Create collection ({form.memberIds.length} members)</button
      >
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
