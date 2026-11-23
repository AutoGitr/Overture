<script lang="ts">
  import LibraryOptions from "./LibraryOptions.svelte";

  let {
    libraries = [],
    selectedIds,
    loading = false,
    error = "",
    onretry,
    emptyMessage = "No libraries found on media server.",
    ontoggle,
    ontoggleall,
  }: {
    libraries?: readonly { id: string; title: string; server_id: number; count?: number | null }[];
    selectedIds: string[];
    loading?: boolean;
    error?: string;
    onretry?: () => void;
    emptyMessage?: string;
    ontoggle: (id: string) => void;
    ontoggleall: (checked: boolean) => void;
  } = $props();
</script>

{#snippet notice()}
  {#if loading}
    <span class="hint">Loading libraries...</span>
  {:else if error}
    <p role="alert">{error}</p>
    {#if onretry}
      <button class="btn btn-ghost btn-sm" onclick={onretry}>Retry</button>
    {/if}
  {:else}
    <span class="hint">{emptyMessage}</span>
  {/if}
{/snippet}

<LibraryOptions
  {libraries}
  selected={selectedIds}
  {ontoggle}
  {ontoggleall}
  notice={loading || error || libraries.length === 0 ? notice : undefined}
/>
