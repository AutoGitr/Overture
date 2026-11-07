<script lang="ts">
  import ImageUp from "@lucide/svelte/icons/image-up";
  import LoaderCircle from "@lucide/svelte/icons/loader-circle";
  import { artPasteState } from "../stores/artPasteState.svelte";

  let target = $derived(artPasteState.target);
  let upload = $derived(target?.upload ?? null);
  let input = $state<HTMLInputElement>();
  let hint = $derived(
    target &&
      [
        `Upload image as ${target.label}`,
        "Saves a JPEG or PNG from this device; pasting an image on the art tab does the same.",
      ].join("\n"),
  );
</script>

{#if target && upload}
  {@const save = upload}
  <button
    type="button"
    class="tab-item"
    aria-label={`Upload image as ${target.label}`}
    title={hint}
    onclick={() => input?.click()}
    disabled={target.busy}
  >
    {#if target.busy}
      <LoaderCircle size={16} class="animate-spin" />
    {:else}
      <ImageUp size={16} />
    {/if}
  </button>
  <input
    bind:this={input}
    type="file"
    accept="image/jpeg,image/png"
    hidden
    onchange={(event) => {
      const file = event.currentTarget.files?.[0];
      event.currentTarget.value = "";
      if (file) void save(file);
    }}
  />
{/if}
