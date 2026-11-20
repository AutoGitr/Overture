<script lang="ts">
  import { librariesByServer } from "../utils/libraries.svelte";
  import CheckboxList from "./CheckboxList.svelte";
  import ServerBadge from "./ServerBadge.svelte";

  let {
    libraries,
    selected,
    ontoggle,
  }: {
    libraries: readonly { id: string; title: string; server_id: number; count?: number | null }[];
    selected: readonly string[];
    ontoggle: (id: string) => void;
  } = $props();

  let groups = $derived(librariesByServer(libraries));
</script>

<div class="groups">
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
