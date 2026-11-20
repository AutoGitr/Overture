<script lang="ts">
  import { settingsState } from "../stores/settingsState.svelte";

  let {
    serverId,
    name,
  }: {
    /** The database's number of the server. */
    serverId: number;
    /** Its name when the line or result was written, for a server no longer configured. */
    name?: string | null;
  } = $props();

  let server = $derived(settingsState.server(serverId));
</script>

<!-- A media server, named as MEDIA_SERVERS names it now and coloured by its kind. -->
<span class={["server-badge", server?.type]} title={server ? `${server.title} (${server.type})` : undefined}
  >{server?.title ?? name ?? `Server ${serverId}`}</span
>

<style>
  .server-badge {
    --server-colour: var(--text-secondary);
    --server-bg: transparent;

    flex: none;
    padding: 0 var(--space-1);
    border: 1px solid oklch(from var(--server-colour) l c h / 0.45);
    border-radius: var(--radius-sm);
    background: var(--server-bg);
    color: var(--server-colour);
    font-size: var(--text-xs);
    font-weight: 500;
    line-height: 16px;
    white-space: nowrap;
  }

  .plex {
    --server-colour: var(--server-plex);
    --server-bg: var(--server-plex-muted);
  }

  .jellyfin {
    --server-colour: var(--server-jellyfin);
    --server-bg: var(--server-jellyfin-muted);
  }

  .emby {
    --server-colour: var(--server-emby);
    --server-bg: var(--server-emby-muted);
  }
</style>
