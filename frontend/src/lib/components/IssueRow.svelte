<script lang="ts">
  import type { Snippet } from "svelte";

  let {
    style,
    checked,
    disabled,
    dimmed = false,
    flagged = false,
    ontoggle,
    title,
    meta,
    status,
  }: {
    style: string;
    checked: boolean;
    disabled: boolean;
    dimmed?: boolean | null;
    flagged?: boolean | null;
    ontoggle: (range: boolean) => void;
    /** The row's first line: what was found. */
    title: Snippet;
    /** The row's second line: where, and what is known about it. */
    meta: Snippet;
    status?: Snippet;
  } = $props();
</script>

<label class={["issue", { dimmed, flagged, actionable: !disabled }]} {style}>
  <span class="checkbox">
    <input type="checkbox" {checked} {disabled} onclick={(event) => ontoggle(event.shiftKey)} />
  </span>
  <span class="details">
    <span class="line">{@render title()}</span>
    <span class="line">{@render meta()}</span>
  </span>
  <span class="status">{@render status?.()}</span>
</label>

<style>
  .issue {
    display: grid;
    grid-template-columns: 20px 1fr 24px;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-2);
    border-radius: var(--radius-sm);
    background: var(--bg-secondary);
    font-size: var(--text-xs);
    border-bottom: var(--space-1) solid var(--bg-primary);
    box-sizing: border-box;
  }

  .dimmed {
    opacity: 0.5;
  }

  .flagged {
    border-left: 2px solid var(--warning);
  }

  .actionable {
    cursor: pointer;
  }

  .actionable:hover {
    background: var(--bg-tertiary);
  }

  .checkbox,
  .status {
    display: flex;
    align-items: center;
  }

  .status {
    justify-content: center;
  }

  .details {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    min-width: 0;
  }

  .line {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    min-width: 0;
  }

  /* The lines are the panels' snippets, so their shared parts are styled here.
     Badges keep their size; names give way only to them, and a folder takes
     whatever room the line has left. */
  .issue :global {
    .badge {
      flex: none;
    }

    .issue-name {
      flex: 0 1 auto;
      color: var(--text-secondary);
    }

    .issue-folder {
      flex: 1 1 auto;
      color: var(--text-tertiary);
    }

    .status-ok {
      color: var(--success);
      font-weight: 700;
    }

    .status-err {
      color: var(--danger);
      font-weight: 700;
    }
  }
</style>
