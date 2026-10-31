<script lang="ts">
  import { createQuery } from "@tanstack/svelte-query";
  import type { Snippet } from "svelte";
  import {
    getLibrariesOptions,
    listCollectionGroupsOptions,
  } from "../../generated/rest/@tanstack/svelte-query.gen";
  import { UNGROUPED_GROUP } from "../../generated/settings";
  import { uiState } from "../stores/uiState.svelte";
  import PopupShell from "../components/PopupShell.svelte";
  import CollectionGroupSettings from "../components/CollectionGroupSettings.svelte";
  import CollectionGroupActions from "../components/CollectionGroupActions.svelte";
  import WorkflowSections from "../components/WorkflowSections.svelte";
  import DataStatus from "../components/DataStatus.svelte";
  let name = $state(uiState.collectionGroupToEdit);
  let newName = $state(uiState.collectionGroupToEdit);
  /** The group being configured has not been saved yet. */
  let unsaved = $state(false);
  const groups = createQuery(() =>
    listCollectionGroupsOptions({ query: { media_type: uiState.sidebarTab } }),
  );
  const libraries = createQuery(() =>
    getLibrariesOptions({ query: { media_type: uiState.sidebarTab } }),
  );
  /** The open group's save actions, which its settings hand over. */
  let groupFooter = $state<Snippet | null>(null);
</script>

<PopupShell title="Collection groups" size="wide" onclose={() => uiState.closePopup()}>
  <p class="hint">
    Collections in a group share its defaults, and a group can be a set that creates its
    collections.
  </p>
  <DataStatus
    label="collection groups"
    error={groups.error}
    loading={groups.isFetching}
    hasData={groups.data !== undefined}
    onretry={() => groups.refetch()}
  />
  <DataStatus
    label="libraries"
    error={libraries.error}
    loading={libraries.isFetching}
    hasData={libraries.data !== undefined}
    onretry={() => libraries.refetch()}
  />
  <label class="form-label">
    Group
    <select
      value={groups.data?.includes(name) ? name : "__new__"}
      onchange={(event) => {
        name = event.currentTarget.value === "__new__" ? "" : event.currentTarget.value;
        unsaved = false;
      }}
    >
      <option value="__new__">Create new group...</option>
      {#each groups.data ?? [] as group (group)}<option value={group}>{group}</option>{/each}
    </select>
  </label>
  {#if !groups.data?.includes(name)}
    <label class="form-label"
      >Group name<input maxlength="200" bind:value={newName} placeholder="e.g. Franchises" /></label
    >
    <button
      class="btn btn-secondary"
      type="button"
      disabled={!newName.trim()}
      onclick={() => {
        name = newName.trim();
        unsaved = true;
      }}>Configure</button
    >
  {/if}
  {#if name.trim()}
    <WorkflowSections>
      {#if groups.data?.includes(name) && !unsaved && name !== UNGROUPED_GROUP}
        <CollectionGroupActions
          group={name}
          mediaType={uiState.sidebarTab}
          onrename={(replacement) => {
            uiState.collectionGroupChanged(name, replacement);
            name = replacement;
          }}
          ondelete={() => {
            uiState.collectionGroupChanged(name, "");
            name = "";
            newName = "";
          }}
        />
      {/if}
      {#key `${uiState.sidebarTab}:${name.trim()}`}<CollectionGroupSettings
          group={name.trim()}
          mediaType={uiState.sidebarTab}
          libraries={libraries.data ?? []}
          onfooterchange={(footer) => (groupFooter = footer)}
          onsave={() => {
            if (!unsaved) return;
            uiState.collectionGroupChanged("", name.trim());
            unsaved = false;
            if (uiState.pickingCollectionGroup) uiState.closePopup();
          }}
        />{/key}
    </WorkflowSections>
  {/if}

  {#snippet footer()}
    <button type="button" class="btn btn-secondary" onclick={() => uiState.closePopup()}
      >Close</button
    >
    {#if name.trim() && groupFooter}
      {@render groupFooter()}
    {/if}
  {/snippet}
</PopupShell>

<style>
  .form-label {
    display: grid;
    gap: var(--space-2);
    margin-block: var(--space-4);
  }
</style>
