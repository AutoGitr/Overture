<script lang="ts">
  let { message, onretry }: { message: string; onretry: () => void } = $props();
</script>

<!-- Why a list's lines failed to load, over the lines it still holds. -->
<div class="load-error" role="alert">
  <span>{message}</span>
  <button type="button" class="btn btn-ghost btn-sm" onclick={onretry}>Retry</button>
</div>

<style>
  .load-error {
    position: absolute;
    inset: auto var(--space-2) var(--space-2);
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    padding: var(--space-1) var(--space-2);
    border-radius: var(--radius-sm);
    background: var(--bg-elevated);
    color: var(--danger);
    font-family: var(--font-sans);
    font-size: var(--text-xs);
    box-shadow: var(--shadow-md);
  }
</style>
