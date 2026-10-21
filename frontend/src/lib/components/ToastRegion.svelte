<script lang="ts">
  import { onMount } from "svelte";
  import { notificationState } from "../stores/notificationState.svelte";
  import Toast from "./Toast.svelte";

  /** Set on the app root's region; every modal dialog mounts its own. */
  let { root = false }: { root?: boolean } = $props();

  // A modal makes everything outside it inert, so only the topmost modal's
  // region renders: notifications stay visible and clickable above it.
  const id = Symbol("toast-region");
  onMount(() => notificationState.host(id, root));
  let active = $derived(notificationState.activeHost === id);
</script>

{#if active && (notificationState.pinned.length || notificationState.toasts.length)}
  <section class="toast-region" aria-label="Notifications">
    {#each notificationState.pinned as content (content)}
      {@render content()}
    {/each}
    {#each notificationState.toasts as toast (toast.id)}
      <Toast {toast} />
    {/each}
  </section>
{/if}

<style>
  .toast-region {
    position: fixed;
    right: calc(var(--space-4) + var(--safe-area-right));
    bottom: calc(var(--space-4) + var(--safe-area-bottom));
    z-index: 3000;
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    width: min(400px, calc(100vw - var(--space-8)));
    max-height: calc(100dvh - var(--space-8));
    overflow-y: auto;
    text-align: left;
    pointer-events: none;
  }

  @media (max-width: 768px), (max-height: 500px) and (pointer: coarse) {
    .toast-region {
      left: calc(var(--space-2) + var(--safe-area-left));
      right: calc(var(--space-2) + var(--safe-area-right));
      bottom: calc(var(--space-2) + var(--safe-area-bottom));
      width: auto;
    }
  }
</style>
