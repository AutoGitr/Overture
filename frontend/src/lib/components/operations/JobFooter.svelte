<script lang="ts">
  import type { Snippet } from "svelte";
  import PendingButton from "../PendingButton.svelte";

  /**
   * The footer every operation tab shares: what starts a run, Stop while one
   * runs, and Clear Results once it has finished. A tab supplies only the
   * buttons that differ.
   */
  let {
    hasResults,
    running,
    blocked,
    stopping,
    onstop,
    clear,
    runningNote,
    start,
    finished,
  }: {
    /** A run exists, so its results show instead of the configuration. */
    hasResults: boolean;
    running: boolean;
    /** Why a run cannot start now, or `null`. */
    blocked: string | null;
    stopping: boolean;
    onstop: () => unknown;
    clear: { mutate: () => void; isPending: boolean };
    /** Said beside Stop while the run works. */
    runningNote?: Snippet;
    /** The buttons that save or start a run. */
    start: Snippet;
    /** Actions on the finished run's results, after Clear Results. */
    finished?: Snippet;
  } = $props();
</script>

{#if !hasResults}
  {#if blocked}
    <span class="popup-footer-note" role="status">{blocked}</span>
  {/if}
  {@render start()}
{:else if running}
  {@render runningNote?.()}
  <PendingButton class="btn btn-danger" onclick={onstop} pending={stopping}>
    {stopping ? "Stopping..." : "Stop"}
  </PendingButton>
{:else}
  <PendingButton
    class="btn btn-ghost"
    onclick={() => clear.mutate()}
    pending={clear.isPending}
    pendingLabel="Clearing..."
  >
    Clear Results
  </PendingButton>
  {@render finished?.()}
{/if}
