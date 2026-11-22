<script lang="ts">
  import { settingsState } from "../stores/settingsState.svelte";
  import ServerBadge from "./ServerBadge.svelte";

  let { library }: { library: { title: string; server_id: number } } = $props();
</script>

<!-- A library as people know it, after its server in the server's colours
     when more than one is configured, as settingsState.libraryLabel names it. -->
<span class="library-name">
  {#if settingsState.multipleServers}
    <ServerBadge serverId={library.server_id} />
  {/if}
  <span>{library.title}</span>
</span>

<style>
  .library-name {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    min-width: 0;
  }
</style>
