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
     * Every size is one column of content, centred, as tall as it is up to
     * the screen's height, past which its body scrolls; it is as wide as the
     * size allows, and narrower only when the screen is.
     * - `dialog`: a short question.
     * - `form`: settings and choices.
     * - `wide`: work that needs the width, such as operations. It keeps one
     *   height, so switching its tabs never resizes or moves it.
     */
    size?: "dialog" | "form" | "wide";
    /** Optional glyph rendered before the title. */
    icon?: Snippet;
    /**
     * A `PopupTabs` shown under the title, part of the header that never
     * scrolls. Set `--popup-glow-at` to the active tab's centre, as a fraction
     * of the tabs' width, and the header's glow follows it.
     */
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
    padding: var(--safe-area-top) calc(var(--popup-margin) + var(--safe-area-right))
      var(--safe-area-bottom) calc(var(--popup-margin) + var(--safe-area-left));
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
    height: min(100%, 880px);
  }

  .popup-header {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
    padding: var(--space-4) var(--popup-pad) var(--space-3);
    flex-shrink: 0;
    position: relative;
    isolation: isolate;
    border-bottom: var(--border-subtle);
  }

  /* Centred on the header's padded content, so a fraction of the tabs' width
     lands on a tab; without tabs it sits at the top-left corner. */
  .popup-header::before {
    content: "";
    position: absolute;
    z-index: -1;
    top: 0;
    bottom: 0;
    left: calc(var(--popup-pad) + (100% - 2 * var(--popup-pad)) * var(--popup-glow-at, 0));
    width: 70%;
    translate: -50% 0;
    background: radial-gradient(
      ellipse 50% 100% at 50% 0%,
      oklch(from var(--accent) l c h / 0.24),
      transparent
    );
    pointer-events: none;
    transition: left 0.35s cubic-bezier(0.16, 1, 0.3, 1);
  }

  @media (prefers-reduced-motion: reduce) {
    .popup-header::before {
      transition: none;
    }
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
    flex: 1 1 auto;
    min-height: 0;
    overflow-x: hidden;
    overflow-y: auto;
    overscroll-behavior: contain;
  }

  .popup-footer {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: var(--space-3);
    padding: var(--space-3) var(--popup-pad) var(--popup-pad);
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

  .popup-info {
    padding: var(--space-2) var(--popup-pad);
    font-size: var(--text-xs);
    color: var(--text-secondary);
    background: var(--bg-secondary);
    border-bottom: var(--border-subtle);
    line-height: 1.5;
  }

  .popup-body-content {
    padding: var(--space-2) var(--popup-pad);
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
    .popup-footer :global(> .btn) {
      min-height: 44px;
    }
  }

  @media (max-width: 480px), (max-height: 500px) and (pointer: coarse) {
    .popup-header h2 {
      font-size: var(--text-lg);
    }
    .popup-footer :global(> .btn) {
      flex: 1;
    }
  }
</style>
