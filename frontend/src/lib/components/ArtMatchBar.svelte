<script lang="ts">
  import Check from "@lucide/svelte/icons/check";
  import CircleAlert from "@lucide/svelte/icons/circle-alert";
  import LoaderCircle from "@lucide/svelte/icons/loader-circle";
  import type { Snippet } from "svelte";
  import type { ArtType } from "../../generated/rest/types.gen";
  import type { ArtMatch } from "../utils/artMatch.svelte";
  import { MAX_MATCH_THRESHOLD, MIN_MATCH_THRESHOLD } from "../utils/matchStatus";

  let {
    match,
    artType,
    canMatch,
    saving,
    pending,
    onmatch,
    entry,
  }: {
    match: ArtMatch;
    artType: ArtType;
    canMatch: boolean;
    saving: boolean;
    /** A match runs, or is about to run on its own. */
    pending: boolean;
    onmatch: () => void;
    /** The URL entry, when it is open. */
    entry?: Snippet;
  } = $props();

  const thresholdId = $props.id();
</script>

<div class="match-bar">
  <div class="status">
    {#if !canMatch && !saving}
      <span class="text-muted">Choose artwork to add this title</span>
    {:else if saving}
      <LoaderCircle size={14} class="animate-spin" />
      <span class="text-muted">Saving selected art...</span>
    {:else if pending}
      <LoaderCircle size={14} class="animate-spin" />
      <span class="text-muted">Matching...</span>
    {:else if match.ran && match.status}
      {#if match.settled}
        <Check size={14} class="text-success" />
      {:else if match.results !== null}
        <CircleAlert size={14} class="text-warning" />
      {/if}
      <span>{match.status}</span>
    {:else}
      <span class="text-muted">Run match to find candidates</span>
    {/if}
  </div>

  {@render entry?.()}

  {#if canMatch}
    <div class="controls">
      <div
        class="threshold"
        title={`Maximum perceptual hash distance (${MIN_MATCH_THRESHOLD}-${MAX_MATCH_THRESHOLD}). Lower is stricter.`}
      >
        <label for={thresholdId} class="threshold-label">Distance &le;</label>
        <input
          id={thresholdId}
          type="number"
          class="threshold-input"
          min={MIN_MATCH_THRESHOLD}
          max={MAX_MATCH_THRESHOLD}
          step="1"
          bind:value={match.threshold}
          onchange={() => match.saveThreshold()}
        />
      </div>
      <button class="btn btn-primary btn-sm" onclick={onmatch} disabled={saving || pending}>
        Match {artType.replace("_", " ")}
      </button>
    </div>
  {/if}
</div>

<style>
  .match-bar {
    display: flex;
    align-items: center;
    gap: var(--space-2) var(--space-3);
    flex-wrap: wrap;
    padding: var(--space-2) var(--space-2) var(--space-2) var(--space-3);
    background: var(--bg-secondary);
    border: var(--border-subtle);
    border-radius: var(--radius-md);
  }

  .status {
    flex: 1 1 auto;
    min-width: 0;
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-size: var(--text-sm);
    color: var(--text-secondary);
  }

  .controls {
    display: flex;
    align-items: center;
    gap: var(--space-3);
  }

  .threshold {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-size: var(--text-sm);
    color: var(--text-secondary);
  }

  .threshold-label {
    font-size: var(--text-sm);
    font-weight: 500;
    color: var(--text-secondary);
    cursor: pointer;
    white-space: nowrap;
  }

  .threshold-input {
    width: 38px;
    padding: var(--space-1) var(--space-1);
    text-align: center;
    font-family: var(--font-mono);
    font-size: var(--text-sm);
    font-weight: 500;
    color: var(--text-primary);
    background: var(--bg-tertiary);
    border: var(--border-subtle);
    border-radius: var(--radius-sm);
    outline: none;
    -moz-appearance: textfield;
    appearance: textfield;
  }

  .threshold-input::-webkit-inner-spin-button,
  .threshold-input::-webkit-outer-spin-button {
    -webkit-appearance: none;
    margin: 0;
  }

  .threshold-input:hover {
    border-color: var(--border-hover);
  }

  .threshold-input:focus {
    border-color: var(--accent);
    box-shadow: 0 0 0 2px var(--accent-muted);
  }
</style>
