<script lang="ts" module>
  export interface ChecklistOption<T extends string = string> {
    id: T;
    label: string;
    count?: number | null;
    checked: boolean;
    /** Shows its state but cannot be toggled; `title` says why. */
    disabled?: boolean;
    title?: string;
  }

  export interface ChecklistGroup<T extends string = string> {
    key: string;
    /** Names the group; empty for a list of one group that needs no name. */
    label: string;
    /** The media server the group's options belong to, shown as its badge. */
    serverId?: number;
    options: ChecklistOption<T>[];
  }
</script>

<script lang="ts" generics="T extends string">
  import type { Snippet } from "svelte";
  import CheckboxList from "./CheckboxList.svelte";
  import SelectAll from "./SelectAll.svelte";
  import ServerBadge from "./ServerBadge.svelte";

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
    groups: ChecklistGroup<T>[];
    /** Whether "everything" is chosen; by default, whether every option is checked. */
    allSelected?: boolean;
    selectAllDisabled?: boolean;
    ontoggle: (groupKey: string, optionId: T) => void;
    ontoggleall: (checked: boolean) => void;
    /** Shown in place of the options: while loading, after an error, or when there are none. */
    notice?: Snippet;
  } = $props();

  const id = $props.id();
  let shownGroups = $derived(groups.filter((group) => group.options.length > 0));
  let options = $derived(shownGroups.flatMap((group) => group.options));
  let everyChecked = $derived(
    allSelected ?? (options.length > 0 && options.every((option) => option.checked)),
  );
</script>

<!-- The list's name and its select-all control share one row, whatever the
     list holds, so choosing everything never takes a line of its own. -->
<div class="checklist" role="group" aria-labelledby="{id}-label">
  <div class="heading-row">
    <span id="{id}-label" class="form-label">{label}</span>
    <SelectAll
      checked={everyChecked}
      indeterminate={!everyChecked && options.some((option) => option.checked)}
      noun={label.toLowerCase()}
      disabled={selectAllDisabled}
      ontoggle={ontoggleall}
    />
  </div>
  {#if notice}
    {@render notice()}
  {:else}
    {#each shownGroups as group (group.key)}
      <div class="group" role={group.label ? "group" : undefined} aria-label={group.label || undefined}>
        {#if group.serverId !== undefined && group.label}
          <span class="server-heading" aria-hidden="true"><ServerBadge serverId={group.serverId} /></span>
        {:else if group.label}
          <span class="caps-label" aria-hidden="true">{group.label}</span>
        {/if}
        <CheckboxList
          options={group.options.map((option) => ({
            value: option.id,
            label: option.label,
            count: option.count ?? undefined,
            disabled: option.disabled,
            title: option.title,
          }))}
          selected={group.options.filter((option) => option.checked).map((option) => option.id)}
          ontoggle={(optionId) => ontoggle(group.key, optionId)}
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
    min-width: 0;
  }

  .group {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    min-width: 0;
  }

  .server-heading {
    display: flex;
  }
</style>
