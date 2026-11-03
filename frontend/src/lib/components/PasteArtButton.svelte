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
    class="tab-item"
    aria-label={`Paste URL & save as ${target.label}`}
    title={hint}
    onclick={() => target.paste()}
    disabled={target.busy}
  >
    {#if target.busy}
      <LoaderCircle size={16} class="animate-spin" />
    {:else}
      <ClipboardPaste size={16} />
    {/if}
  </button>
{/if}
