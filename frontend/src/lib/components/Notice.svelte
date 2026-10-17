<script lang="ts">
  import CircleAlert from "@lucide/svelte/icons/circle-alert";
  import CircleCheck from "@lucide/svelte/icons/circle-check";
  import Info from "@lucide/svelte/icons/info";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import X from "@lucide/svelte/icons/x";
  import type { Snippet } from "svelte";
  import type { NoticeAction, NoticeTone } from "../stores/notificationState.svelte";
  import { delayedFlag } from "../utils/delayedFlag.svelte";

  let {
    tone,
    title,
    message,
    action,
    ondismiss,
    children,
  }: {
    tone: NoticeTone;
    title?: string;
    message: string;
    action?: NoticeAction;
    ondismiss?: () => void;
    /** Extra markup drawn inside the card, such as a toast's countdown. */
    children?: Snippet;
  } = $props();

  const ICONS = { success: CircleCheck, info: Info, warning: TriangleAlert, error: CircleAlert };
  let Icon = $derived(ICONS[tone]);
  const showPending = delayedFlag(() => !!action?.pending);
</script>

<div class={["notice", `notice-${tone}`]} role={tone === "error" ? "alert" : "status"}>
  <span class="notice-icon" aria-hidden="true"><Icon size={16} /></span>
  <div class="notice-text">
    {#if title}<strong class="notice-title">{title}</strong>{/if}
    <p class="notice-message">{message}</p>
  </div>
  {#if action}
    <button
      type="button"
      class="btn btn-ghost btn-sm notice-action"
      disabled={showPending.current}
      onclick={() => {
        if (!action.pending) action.run();
      }}
    >
      {showPending.current ? (action.pendingLabel ?? action.label) : action.label}
    </button>
  {/if}
  {#if ondismiss}
    <button
      type="button"
      class="btn btn-ghost btn-icon notice-dismiss"
      aria-label="Dismiss notification"
      onclick={ondismiss}
    >
      <X size={14} />
    </button>
  {/if}
  {@render children?.()}
</div>

<style>
  .notice {
    --tone: var(--info);
    position: relative;
    display: flex;
    align-items: flex-start;
    gap: var(--space-3);
    width: 100%;
    padding: var(--space-3) var(--space-3) var(--space-3) var(--space-4);
    overflow: hidden;
    color: var(--text-primary);
    background: var(--bg-elevated);
    border: var(--border-muted);
    border-radius: var(--radius-md);
    box-shadow: var(--shadow-lg);
    pointer-events: auto;
  }

  /* Tone stripe on the leading edge. */
  .notice::before {
    content: "";
    position: absolute;
    inset: 0 auto 0 0;
    width: 3px;
    background: var(--tone);
  }

  .notice-success {
    --tone: var(--success);
  }

  .notice-warning {
    --tone: var(--warning);
  }

  .notice-error {
    --tone: var(--danger);
  }

  .notice-icon {
    display: grid;
    flex-shrink: 0;
    place-items: center;
    width: 28px;
    height: 28px;
    color: var(--tone);
    background: oklch(from var(--tone) l c h / 0.14);
    border-radius: var(--radius-full);
  }

  .notice-text {
    display: grid;
    flex: 1;
    gap: 2px;
    min-width: 0;
    padding-top: 4px;
  }

  .notice-title {
    font-size: var(--text-sm);
    font-weight: 600;
    line-height: 1.35;
  }

  .notice-message {
    font-size: var(--text-sm);
    line-height: 1.45;
    overflow-wrap: anywhere;
  }

  .notice-title + .notice-message {
    color: var(--text-secondary);
    font-size: var(--text-xs);
  }

  .notice-action {
    flex-shrink: 0;
    align-self: center;
    color: var(--tone);
    font-weight: 600;
  }

  .notice-dismiss {
    flex-shrink: 0;
    width: 28px;
    height: 28px;
    padding: 0;
    color: var(--text-tertiary);
  }

  .notice-dismiss:hover {
    color: var(--text-primary);
  }
</style>
