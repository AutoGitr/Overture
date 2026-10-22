<script lang="ts">
  import {
    notificationState,
    TOAST_DURATION_MS,
    type Toast,
  } from "../stores/notificationState.svelte";
  import Notice from "./Notice.svelte";

  let { toast }: { toast: Toast } = $props();

  // The countdown belongs to the store: when a modal opens or closes, this
  // toast is re-rendered in another region and must continue, not restart.
  let clock = $derived(notificationState.clock(toast.id));
  let elapsed = $derived(clock.elapsed);

  let hovered = $state(false);
  let focused = $state(false);
  /** Hovering or focusing a toast holds it open so it can be read or acted on. */
  let held = $derived(hovered || focused);

  $effect(() => {
    if (!held) return;
    clock.hold();
    return () => clock.release();
  });

  const dismiss = () => notificationState.dismiss(toast.id);
</script>

<div
  class="toast"
  role="presentation"
  onpointerenter={() => (hovered = true)}
  onpointerleave={() => (hovered = false)}
  onfocusin={() => (focused = true)}
  onfocusout={(event) => {
    focused = event.currentTarget.contains(event.relatedTarget as Node | null);
  }}
>
  <Notice
    tone={toast.tone}
    title={toast.title}
    message={toast.message}
    action={toast.action && {
      ...toast.action,
      run: () => {
        toast.action?.run();
        dismiss();
      },
    }}
    ondismiss={dismiss}
  >
    <span
      class={["toast-countdown", { held }]}
      style:animation-duration="{TOAST_DURATION_MS}ms"
      style:animation-delay="-{elapsed}ms"
      aria-hidden="true"
    ></span>
  </Notice>
</div>

<style>
  .toast-countdown {
    position: absolute;
    right: 0;
    bottom: 0;
    left: 0;
    height: 2px;
    background: var(--tone);
    opacity: 0.5;
    transform-origin: left;
    animation-name: countdown;
    animation-timing-function: linear;
    animation-fill-mode: forwards;
  }

  .toast-countdown.held {
    animation-play-state: paused;
  }

  @keyframes countdown {
    to {
      transform: scaleX(0);
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .toast-countdown {
      display: none;
    }
  }
</style>
