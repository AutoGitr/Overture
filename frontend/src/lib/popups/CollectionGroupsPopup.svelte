<script lang="ts">
  import { createQuery } from "@tanstack/svelte-query";
  import type { Snippet } from "svelte";
  import { listCollectionGroupsOptions } from "../../generated/rest/@tanstack/svelte-query.gen";
  import { TEXT_LIMITS, UNGROUPED_GROUP } from "../../generated/settings";
  import { uiState } from "../stores/uiState.svelte";
  import PopupShell from "../components/PopupShell.svelte";
  import CollectionGroupSettings from "../components/CollectionGroupSettings.svelte";
  import CollectionGroupActions from "../components/CollectionGroupActions.svelte";
  import WorkflowSections from "../components/WorkflowSections.svelte";
  import DataStatus from "../components/DataStatus.svelte";
  import Select from "../components/Select.svelte";
  import { toOptions } from "../utils/selectOptions";
  import { NEW_GROUP_OPTION } from "../utils/collectionGroups.svelte";
  import { setSectionView } from "../stores/sectionState.svelte";
  import { allLibraries } from "../utils/libraries.svelte";
  setSectionView("collection-groups");
  const groupId = $props.id();
  let name = $state(uiState.collectionGroupToEdit);
  let newName = $state(uiState.collectionGroupToEdit);
  /** The group being configured has not been saved yet. */
  let unsaved = $state(false);
  const groups = createQuery(() => listCollectionGroupsOptions());
  let groupChoices = $derived([NEW_GROUP_OPTION, ...toOptions(groups.data ?? [])]);
  const libraries = allLibraries();
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
  <div class="form-label">
    <label for={groupId}>Group</label>
    <Select
      id={groupId}
      options={groupChoices}
      bind:value={
        () => (groups.data?.includes(name) ? name : NEW_GROUP_OPTION.value),
        (chosen) => {
          name = chosen === NEW_GROUP_OPTION.value ? "" : chosen;
          unsaved = false;
        }
      }
    />
  </div>
  {#if !groups.data?.includes(name)}
    <label class="form-label"
      >Group name<input maxlength={TEXT_LIMITS.groupName} bind:value={newName} placeholder="e.g. Franchises" /></label
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
      {#key name.trim()}<CollectionGroupSettings
          group={name.trim()}
          libraries={libraries.data ?? []}
          onfooterchange={(footer) => (groupFooter = footer)}
          onsave={() => {
            if (!unsaved) return;
            uiState.collectionGroupChanged("", name.trim());
            unsaved = false;
            if (uiState.pickingCollectionGroup) uiState.closePopup();
          }}
        />{/key}
      {#if groups.data?.includes(name) && !unsaved && name !== UNGROUPED_GROUP}
        <CollectionGroupActions
          group={name}
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
