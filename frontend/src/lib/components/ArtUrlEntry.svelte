<script lang="ts">
  import X from "@lucide/svelte/icons/x";

  let {
    saving,
    onsave,
    oncancel,
  }: {
    saving: boolean;
    onsave: (text: string) => void;
    oncancel: () => void;
  } = $props();

  let url = $state("");
</script>

<form
  class="url-entry"
  onsubmit={(event) => {
    event.preventDefault();
    onsave(url);
  }}
>
  <input
    type="url"
    class="url-input"
    placeholder="Paste image URL..."
    aria-label="Image URL"
    bind:value={url}
    onkeydown={(event) => {
      if (event.key === "Escape") oncancel();
    }}
    {@attach (node) => node.focus()}
  />
  <button type="submit" class="btn btn-secondary btn-sm" disabled={saving || !url.trim()}>
    Save
  </button>
  <button
    type="button"
    class="btn btn-ghost btn-icon btn-sm"
    aria-label="Cancel URL entry"
    title="Cancel"
    onclick={oncancel}
  >
    <X size={14} />
  </button>
</form>

<style>
  .url-entry {
    display: flex;
    align-items: center;
    gap: var(--space-1);
    flex: 1 1 260px;
    min-width: 0;
  }

  .url-input {
    flex: 1;
    min-width: 0;
    padding: var(--space-1) var(--space-2);
    font-size: var(--text-sm);
  }
</style>
