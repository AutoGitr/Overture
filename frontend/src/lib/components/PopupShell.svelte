<script lang="ts">
  import CircleHelp from "@lucide/svelte/icons/circle-help";
  import X from "@lucide/svelte/icons/x";
  import { onMount, type Snippet } from "svelte";
  import ToastRegion from "./ToastRegion.svelte";

  let {
    title,
    size = "form",
    icon,
    tabs,
    info,
    about,
    children,
    footer,
    onclose,
  }: {
    title: string;
    /**
     * How wide the popup is; it is narrower only when the screen is. Every
     * popup is centred and exactly as tall as its content, up to the
     * screen's height: there its job lists give way first, then its body
     * scrolls.
     * - `dialog`: a short question.
     * - `form`: settings and choices.
     * - `wide`: work that needs the width, such as operations.
     */
    size?: "dialog" | "form" | "wide";
    /** Optional glyph rendered before the title. */
    icon?: Snippet;
    /** A `PopupTabs` shown under the title, part of the header that never scrolls. */
    tabs?: Snippet;
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
  <div class={["popup-content", size]}>
    <div class="popup-header">
      <div class="header-row">
        <div class="header-title">
          {@render icon?.()}
          <h2 id={titleId}>{title}</h2>
        </div>
        <div class="header-buttons">
          {#if about}
            <button
              class={["btn btn-ghost btn-icon", { active: aboutOpen }]}
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
      {@render tabs?.()}
    </div>

    <div class="popup-body">
      {#if about && aboutOpen}
        <div class="popup-info" id={aboutId}>
          {@render about()}
        </div>
      {/if}
      {#if info}
        <div class="popup-info">
          {@render info()}
        </div>
      {/if}
      <div class="popup-body-content">
        {@render children()}
      </div>
    </div>

    {#if footer}
      <div class="popup-footer">
        {@render footer()}
      </div>
    {/if}
  </div>
  <ToastRegion />
</dialog>

<style>
  .popup-overlay {
    --popup-margin: var(--space-3);
    /* Thinner on short screens, where every row of content counts. */
    --popup-margin-block: min(var(--popup-margin), 2dvh);

    position: fixed;
    inset: 0;
    z-index: 1000;
    width: 100%;
    height: 100%;
    height: 100dvh;
    max-width: none;
    max-height: 100dvh;
    margin: 0;
    border: 0;
    color: var(--text-primary);
    align-items: center;
    justify-content: center;
    background: transparent;
    /* Clipped, not hidden: neither the overlay nor the popup is a scroll
       container, so focusing a field scrolls only the body. */
    overflow: clip;
    overscroll-behavior: contain;
    padding: calc(var(--popup-margin-block) + var(--safe-area-top))
      calc(var(--popup-margin) + var(--safe-area-right))
      calc(var(--popup-margin-block) + var(--safe-area-bottom))
      calc(var(--popup-margin) + var(--safe-area-left));
  }

  .popup-overlay[open] {
    display: flex;
  }

  .popup-overlay::backdrop {
    background: var(--surface-overlay);
    backdrop-filter: blur(8px);
    -webkit-backdrop-filter: blur(8px);
  }

  .popup-content {
    position: relative;
    z-index: 1;
    background: var(--bg-elevated);
    border: var(--border-muted);
    border-radius: var(--radius-lg);
    box-shadow: var(--shadow-lg);

    --popup-pad: var(--space-5);

    max-width: 100%;
    max-height: 100%;
    min-height: 0;
    overflow: clip;

    display: flex;
    flex-direction: column;
  }

  .popup-content.dialog {
    width: 440px;
  }

  .popup-content.form {
    width: 720px;
  }

  .popup-content.wide {
    width: 1040px;
  }

  .popup-header {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    padding: var(--space-3) var(--popup-pad);
    flex-shrink: 0;
    border-bottom: var(--border-subtle);
  }

  .header-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
  }

  .header-title {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    min-width: 0;
  }

  .header-title :global(svg) {
    color: var(--accent);
  }

  .header-buttons {
    display: flex;
    align-items: center;
    gap: var(--space-1);
  }

  .header-buttons :global(.btn.active) {
    color: var(--accent);
    background: var(--accent-muted);
  }

  .popup-header h2 {
    font-size: var(--text-xl);
    font-weight: 700;
    letter-spacing: -0.01em;
    overflow-wrap: anywhere;
  }

  /* The info strip spans the body's width and scrolls with it; only the
     content is padded. */
  .popup-body {
    display: flex;
    flex-direction: column;
    flex: 1 1 auto;
    min-height: 0;
    overflow-x: hidden;
    overflow-y: auto;
    overscroll-behavior: contain;
  }

  .popup-body > * {
    flex: none;
  }

  /* Job panels' lists give way to the screen's height before the body
     scrolls. Only then may the content be shorter than what it holds: an
     overflowing box loses its bottom padding from the scroll range. */
  .popup-body-content:has(:global(.job-panel)) {
    display: flex;
    flex-direction: column;
    flex: 0 1 auto;
    min-height: 0;
  }

  .popup-footer {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: var(--space-3);
    padding: var(--space-3) var(--popup-pad);
    flex-shrink: 0;
    border-top: var(--border-subtle);
  }

  .popup-footer :global(.popup-footer-note) {
    flex: 1;
    color: var(--text-secondary);
    font-size: var(--text-xs);
  }

  .popup-footer :global(> .btn) {
    min-height: 32px;
  }

  /* Destructive and reset actions sit apart, at the start. */
  .popup-footer :global(> .footer-start) {
    margin-inline-end: auto;
  }

  .popup-info {
    padding: var(--space-2) var(--popup-pad);
    font-size: var(--text-xs);
    color: var(--text-secondary);
    background: var(--bg-secondary);
    border-bottom: var(--border-subtle);
    line-height: 1.5;
  }

  /* One text size for every row, label and field in a popup. */
  .popup-body-content {
    padding: var(--space-2) var(--popup-pad);
    font-size: var(--text-sm);
  }

  .popup-info + .popup-body-content {
    padding-top: var(--space-3);
  }

  @media (max-width: 640px) {
    .popup-content {
      --popup-pad: var(--space-4);
    }
    .popup-footer {
      flex-wrap: wrap;
    }
  }

  /* Sized by the pointer, not the window: a narrow desktop window keeps
     desktop buttons. */
  @media (hover: none) and (pointer: coarse) {
    .popup-footer :global(> .btn) {
      min-height: 44px;
    }
  }

  @media (max-width: 480px), (max-height: 500px) and (pointer: coarse) {
    .popup-header h2 {
      font-size: var(--text-lg);
    }
  }
</style>
