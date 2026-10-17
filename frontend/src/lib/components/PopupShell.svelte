<script lang="ts">
  import CircleHelp from "@lucide/svelte/icons/circle-help";
  import X from "@lucide/svelte/icons/x";
  import { onMount, type Snippet } from "svelte";
  import ToastRegion from "./ToastRegion.svelte";

  let {
    title,
    width,
    fill = false,
    icon,
    info,
    about,
    children,
    footer,
    onclose,
  }: {
    title: string;
    width?: string;
    /**
     * Let the body's own sections size themselves to the popup instead of
     * scrolling it: a results view then shrinks its lists to fit rather than
     * pushing the popup past the screen.
     */
    fill?: boolean;
    /** Optional glyph rendered before the title. */
    icon?: Snippet;
    info?: Snippet;
    /** What the popup is for, shown only when asked for from the header. */
    about?: Snippet;
    children: Snippet;
    footer?: Snippet;
    onclose: () => void;
  } = $props();

  const titleId = $props.id();
  const aboutId = `${titleId}-about`;
  let aboutOpen = $state(false);
  let dialog: HTMLDialogElement;
  let closeButton: HTMLButtonElement;
  let backdropPressed = false;

  onMount(() => {
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    dialog.showModal();
    closeButton.focus({ preventScroll: true });
    return () => {
      dialog.close();
      if (opener?.isConnected) opener.focus({ preventScroll: true });
    };
  });
</script>

<dialog
  bind:this={dialog}
  class="popup-overlay"
  aria-modal="true"
  aria-labelledby={titleId}
  oncancel={(event) => {
    event.preventDefault();
    onclose();
  }}
  onpointerdown={(event) => (backdropPressed = event.target === dialog)}
  onclick={(event) => {
    if (backdropPressed && event.target === dialog) onclose();
    backdropPressed = false;
  }}
>
  <div class="popup-content" style:width>
    <div class="popup-header">
      {#if icon}
        <div class="header-title">
          {@render icon()}
          <h2 id={titleId}>{title}</h2>
        </div>
      {:else}
        <h2 id={titleId}>{title}</h2>
      {/if}
      <div class="header-buttons">
        {#if about}
          <button
            class="btn btn-ghost btn-icon"
            class:active={aboutOpen}
            type="button"
            title="What does this do?"
            aria-label="What does this do?"
            aria-expanded={aboutOpen}
            aria-controls={aboutId}
            onclick={() => (aboutOpen = !aboutOpen)}
          >
            <CircleHelp size={18} />
          </button>
        {/if}
        <button
          class="btn btn-ghost btn-icon"
          type="button"
          aria-label="Close popup"
          bind:this={closeButton}
          onclick={onclose}
        >
          <X size={18} />
        </button>
      </div>
    </div>

    {#if about && aboutOpen}
      <div class="popup-info" id={aboutId}>
        {@render about()}
      </div>
    {/if}

    {#snippet infoStrip()}
      {#if info}
        <div class="popup-info">
          {@render info()}
        </div>
      {/if}
    {/snippet}

    <!-- Info scrolls away with a scrolling body; a fill body keeps it pinned. -->
    {#if fill}
      {@render infoStrip()}
    {/if}

    <div class="popup-body" class:fill>
      {#if !fill}
        {@render infoStrip()}
      {/if}
      {@render children()}
    </div>

    {#if footer}
      <div class="popup-footer">
        {@render footer()}
      </div>
    {/if}
  </div>
  <ToastRegion />
</dialog>
