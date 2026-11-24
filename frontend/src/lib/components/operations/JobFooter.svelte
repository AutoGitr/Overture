<script lang="ts">
  import type { Snippet } from "svelte";
  import type { OperationRun } from "../../utils/operationRun.svelte";
  import PendingButton from "../PendingButton.svelte";

  /**
   * The footer every operation tab shares: what starts a run, Stop while one
   * runs, and Clear results once it has finished. A tab supplies only the
   * buttons that differ.
   */
  let {
    run,
    onstop,
    runningNote,
    start,
    finished,
  }: {
    run: OperationRun;
    /** Stop the running jobs, through `run.stop`. */
    onstop: () => unknown;
    /** Said beside Stop while the run works. */
    runningNote?: Snippet;
    /** The buttons that save or start a run; `run.blocked` is said beside them. */
    start: Snippet;
    /** Actions on the finished run's results. */
    finished?: Snippet;
  } = $props();
</script>

{#if !run.hasResults}
  {#if run.blocked}
    <span class="popup-footer-note" role="status">{run.blocked}</span>
  {/if}
  {@render start()}
{:else if run.running}
  {@render runningNote?.()}
  <PendingButton class="btn btn-danger" onclick={onstop} pending={run.stopping}>
    {run.stopping ? "Stopping..." : "Stop"}
  </PendingButton>
{:else}
  {@render finished?.()}
  <PendingButton
    class="btn btn-ghost"
    onclick={() => run.clearResults.mutate()}
    pending={run.clearResults.isPending}
    pendingLabel="Clearing..."
  >
    Clear results
  </PendingButton>
{/if}
