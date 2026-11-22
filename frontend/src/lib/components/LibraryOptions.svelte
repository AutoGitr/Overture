<script lang="ts">
  import { librariesByServer } from "../utils/libraries.svelte";
  import CheckboxList from "./CheckboxList.svelte";
  import SelectAll from "./SelectAll.svelte";
  import ServerBadge from "./ServerBadge.svelte";

  let {
    libraries,
    selected,
    ontoggle,
    ontoggleall,
  }: {
    libraries: readonly { id: string; title: string; server_id: number; count?: number | null }[];
    selected: readonly string[];
    ontoggle: (id: string) => void;
    /** Choose every library, or none. */
    ontoggleall: (checked: boolean) => void;
  } = $props();

  let groups = $derived(librariesByServer(libraries));
  let allSelected = $derived(
    libraries.length > 0 && libraries.every((library) => selected.includes(library.id)),
  );
</script>

<div class="groups">
  <SelectAll
    checked={allSelected}
    indeterminate={!allSelected && libraries.some((library) => selected.includes(library.id))}
    noun="libraries"
    ontoggle={ontoggleall}
  />
  {#each groups as group (group.server.id)}
    <div class="group" role={group.label ? "group" : undefined} aria-label={group.label || undefined}>
      {#if group.label}
        <span class="server-heading" aria-hidden="true"><ServerBadge serverId={group.server.id} /></span>
      {/if}
      <CheckboxList
        options={group.libraries.map((library) => ({
          value: library.id,
          label: library.title,
          count: library.count ?? undefined,
        }))}
        {selected}
        {ontoggle}
      />
    </div>
  {/each}
</div>

<style>
  .groups,
  .group {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }

  .groups {
    gap: var(--space-3);
  }

  .group {
    gap: var(--space-1);
  }

  .server-heading {
    display: flex;
  }
</style>
