<script lang="ts">
  import { createQuery } from "@tanstack/svelte-query";
  import {
    getLibrariesOptions,
    listCollectionGroupsOptions,
  } from "../../generated/rest/@tanstack/svelte-query.gen";
  import { uiState } from "../stores/uiState.svelte";
  import { settingsState } from "../stores/settingsState.svelte";
  import PopupShell from "../components/PopupShell.svelte";
  import CollectionGroupSettings from "../components/CollectionGroupSettings.svelte";
  import WorkflowSections from "../components/WorkflowSections.svelte";
  import DataStatus from "../components/DataStatus.svelte";
  import CollectionGroupActions from "../components/CollectionGroupActions.svelte";
  import { openSidebarGroup, sidebarGroup } from "../router/routes";
  let name = $state(uiState.collectionGroupToEdit);
  let newName = $state(uiState.collectionGroupToEdit);
  const groups = createQuery(() =>
    listCollectionGroupsOptions({ query: { media_type: uiState.sidebarTab } }),
  );
  const libraries = createQuery(() =>
    getLibrariesOptions({ query: { media_type: uiState.sidebarTab } }),
  );
</script>

<PopupShell title="Collection groups" size="wide" onclose={() => uiState.closePopup()}>
  <p class="hint">
    Groups share defaults. Collections keep explicit overrides. A sort title such as
    01_&#123;title&#125; groups collections together without giving them the same sort title.
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
      onclick={() => (name = newName.trim())}>Configure new group</button
    >
  {/if}
  {#if name.trim()}
    <WorkflowSections>
      {#if groups.data?.includes(name)}
        <CollectionGroupActions
          group={name}
          mediaType={uiState.sidebarTab}
          onrename={(replacement) => {
            uiState.collectionGroupChanged(name, replacement);
            if (sidebarGroup() === name) openSidebarGroup(replacement);
            name = replacement;
            newName = replacement;
          }}
          ondelete={() => {
            uiState.collectionGroupChanged(name, "");
            if (sidebarGroup() === name) openSidebarGroup(null);
            name = "";
            newName = "";
          }}
        />
      {/if}
      {#key `${uiState.sidebarTab}:${name.trim()}`}<CollectionGroupSettings
          group={name.trim()}
          mediaType={uiState.sidebarTab}
          serverType={settingsState.current.media_server}
          libraries={libraries.data ?? []}
        />{/key}
    </WorkflowSections>
  {/if}
</PopupShell>

<style>
  .form-label {
    display: grid;
    gap: var(--space-2);
    margin-block: var(--space-4);
  }
</style>
