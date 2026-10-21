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

  let {
    groups,
    allSelected,
    selectAllDisabled = false,
    ontoggle,
    ontoggleall,
    notice,
  }: {
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

<div class="controls">
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
<div class="list">
  {#if notice}
    {@render notice()}
  {:else}
    {#each shownGroups as group, index (group.key)}
      <div class={["heading", { spaced: index > 0 }]}>{group.label}</div>
      {#each group.options as option (option.id)}
        <label class="checkbox-group">
          <input
            type="checkbox"
            checked={option.checked}
            onchange={() => ontoggle(group.key, option.id)}
          />
          <span>
            {option.label}
            {#if option.count != null}
              <span class="item-count">{option.count}</span>
            {/if}
          </span>
        </label>
      {/each}
    {/each}
  {/if}
</div>

<style>
  .controls {
    margin-bottom: var(--space-2);
  }

  .list {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    max-height: 180px;
    overflow-y: auto;
    padding-right: var(--space-2);
  }

  .heading {
    font-size: var(--text-xs);
    font-weight: 600;
    color: var(--text-tertiary);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: var(--space-1);
  }

  .spaced {
    margin-top: var(--space-3);
  }
</style>
