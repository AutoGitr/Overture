<script lang="ts">
  import CircleQuestionMark from "@lucide/svelte/icons/circle-question-mark";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import { onMount } from "svelte";
  import { notificationState, type ConfirmOptions } from "../stores/notificationState.svelte";
  import PopupShell from "./PopupShell.svelte";

  let { request }: { request: ConfirmOptions } = $props();

  let cancelButton: HTMLButtonElement;
  let confirmButton: HTMLButtonElement;

  onMount(() => {
    // Destructive actions start on the safe choice so Enter cannot slip through.
    (request.destructive ? cancelButton : confirmButton).focus({ preventScroll: true });
  });
</script>

<PopupShell
  title={request.title}
  width="440px"
  onclose={() => notificationState.settleConfirm(false)}
>
  {#snippet icon()}
    <span class={["confirm-icon", { destructive: request.destructive }]} aria-hidden="true">
      {#if request.destructive}<TriangleAlert size={18} />{:else}<CircleQuestionMark
          size={18}
        />{/if}
    </span>
  {/snippet}

  <p class="confirm-message">{request.message}</p>

  {#snippet footer()}
    <button
      type="button"
      class="btn btn-secondary"
      bind:this={cancelButton}
      onclick={() => notificationState.settleConfirm(false)}
    >
      Cancel
    </button>
    <button
      type="button"
      class={["btn", request.destructive ? "btn-danger" : "btn-primary"]}
      bind:this={confirmButton}
      onclick={() => notificationState.settleConfirm(true)}
    >
      {request.confirmLabel ?? "Confirm"}
    </button>
  {/snippet}
</PopupShell>

<style>
  .confirm-icon {
    display: grid;
    flex-shrink: 0;
    place-items: center;
    width: 32px;
    height: 32px;
    color: var(--accent);
    background: var(--accent-muted);
    border-radius: var(--radius-full);
  }

  .confirm-icon.destructive {
    color: var(--danger);
    background: var(--danger-muted);
  }

  .confirm-message {
    color: var(--text-secondary);
    font-size: var(--text-sm);
    line-height: 1.6;
    overflow-wrap: anywhere;
  }
</style>
