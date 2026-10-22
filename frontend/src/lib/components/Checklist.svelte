<script lang="ts" module>
  export interface ChecklistOption {
    id: string;
    label: string;
    count?: number | null;
    checked: boolean;
  }

  export interface ChecklistGroup {
    key: string;
    label: string;
    options: ChecklistOption[];
  }
</script>

<script lang="ts">
  import type { Snippet } from "svelte";
  import CheckboxList from "./CheckboxList.svelte";

  let {
    label,
    groups,
    allSelected,
    selectAllDisabled = false,
    ontoggle,
    ontoggleall,
    notice,
  }: {
    /** Names the list, on the row its select-all control shares. */
    label: string;
    groups: ChecklistGroup[];
    allSelected: boolean;
    selectAllDisabled?: boolean;
    ontoggle: (groupKey: string, optionId: string) => void;
    ontoggleall: (checked: boolean) => void;
    /** Shown in place of the options: while loading, after an error, or when there are none. */
    notice?: Snippet;
  } = $props();

  let shownGroups = $derived(groups.filter((group) => group.options.length > 0));
</script>

<div class="checklist">
  <div class="heading-row">
    <span class="form-label">{label}</span>
    <label class="checkbox-group">
      <input
        type="checkbox"
        checked={allSelected}
        disabled={selectAllDisabled}
        onchange={(event) => ontoggleall(event.currentTarget.checked)}
      />
      <span>{allSelected ? "Deselect All" : "Select All"}</span>
    </label>
  </div>
  {#if notice}
    {@render notice()}
  {:else}
    {#each shownGroups as group (group.key)}
      <div class="group">
        <span class="caps-label">{group.label}</span>
        <CheckboxList
          options={group.options.map((option) => ({
            value: option.id,
            label: option.label,
            count: option.count ?? undefined,
          }))}
          selected={group.options.filter((option) => option.checked).map((option) => option.id)}
          ontoggle={(id) => ontoggle(group.key, id)}
        />
      </div>
    {/each}
  {/if}
</div>

<style>
  .checklist {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }

  .group {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
  }
</style>
