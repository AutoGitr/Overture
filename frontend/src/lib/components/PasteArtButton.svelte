<script lang="ts">
  import ClipboardPaste from "@lucide/svelte/icons/clipboard-paste";
  import LoaderCircle from "@lucide/svelte/icons/loader-circle";
  import { artPasteState } from "../stores/artPasteState.svelte";

  let target = $derived(artPasteState.target);
  let hint = $derived(
    target &&
      [
        `Paste URL & save as ${target.label}`,
        `Saves the image link on your clipboard as this item's ${target.label}.`,
        "Ctrl+V anywhere on the art tab does the same.",
        "Resized, thumbnail and ThePosterDB poster page links are saved as the full-size image.",
        "If the browser blocks clipboard access (e.g. plain HTTP), a URL field opens instead.",
      ].join("\n"),
  );
</script>

{#if target}
  <button
    type="button"
    class="btn btn-secondary btn-icon paste-art-btn"
    aria-label={`Paste URL & save as ${target.label}`}
    title={hint}
    onclick={() => target.paste()}
    disabled={target.busy}
  >
    {#if target.busy}
      <LoaderCircle size={18} class="animate-spin" />
    {:else}
      <ClipboardPaste size={18} />
    {/if}
  </button>
{/if}

<style>
  /* Square, as tall as the sub-tab bar beside it (--tab-height + 8px). */
  .paste-art-btn {
    width: calc(var(--tab-height, 32px) + 8px);
    height: calc(var(--tab-height, 32px) + 8px);
    min-width: 0;
    min-height: 0;
    padding: 0;
  }
</style>
