<script lang="ts">
  import CircleQuestionMark from "@lucide/svelte/icons/circle-question-mark";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import { onMount } from "svelte";
  import { notificationState, type ConfirmRequest } from "../stores/notificationState.svelte";
  import PopupShell from "./PopupShell.svelte";

  let { request }: { request: ConfirmRequest } = $props();

  let cancelButton: HTMLButtonElement;
  let confirmButton: HTMLButtonElement;
  const name = $props.id();
  // Nothing is picked for the user unless the request ticks it: a destructive
  // choice must be made on purpose.
  let chosen = $derived<string[]>(request.initial ?? []);
  let picked = $derived(chosen[0] ?? null);

  function toggle(value: string, on: boolean) {
    chosen = on ? [...chosen, value] : chosen.filter((entry) => entry !== value);
  }

  onMount(() => {
    // Destructive actions, and those waiting for a choice, start on Cancel so Enter cannot slip through.
    (request.destructive || request.choices ? cancelButton : confirmButton).focus({
      preventScroll: true,
    });
  });
</script>

<PopupShell
  title={request.title}
  size="dialog"
  onclose={() => notificationState.settleConfirm(null)}
>
  {#snippet icon()}
    <span class={["confirm-icon", { destructive: request.destructive }]} aria-hidden="true">
      {#if request.destructive}<TriangleAlert size={18} />{:else}<CircleQuestionMark
          size={18}
        />{/if}
    </span>
  {/snippet}

  <p class="confirm-message">{request.message}</p>
  {#if request.choices}
    <div
      class="choices"
      role={request.multiple ? "group" : "radiogroup"}
      aria-label={request.title}
    >
      {#each request.choices as choice, index (choice.value)}
        {@const detail = choice.unavailable ?? choice.description}
        <label class={["choice", { unavailable: !!choice.unavailable }]}>
          {#if request.multiple}
            <input
              type="checkbox"
              value={choice.value}
              checked={chosen.includes(choice.value)}
              onchange={(event) => toggle(choice.value, event.currentTarget.checked)}
              disabled={!!choice.unavailable}
              aria-label={choice.label}
              aria-describedby={detail ? `${name}-${index}` : undefined}
            />
          {:else}
            <input
              type="radio"
              {name}
              value={choice.value}
              checked={picked === choice.value}
              onchange={() => (chosen = [choice.value])}
              disabled={!!choice.unavailable}
              aria-label={choice.label}
              aria-describedby={detail ? `${name}-${index}` : undefined}
            />
          {/if}
          <span class="choice-text">
            <span class="choice-label">{choice.label}</span>
            {#if detail}<span class="hint" id={`${name}-${index}`}>{detail}</span>{/if}
          </span>
        </label>
      {/each}
    </div>
  {/if}

  {#snippet footer()}
    <button
      type="button"
      class="btn btn-secondary"
      bind:this={cancelButton}
      onclick={() => notificationState.settleConfirm(null)}
    >
      Cancel
    </button>
    <button
      type="button"
      class={["btn", request.destructive ? "btn-danger" : "btn-primary"]}
      bind:this={confirmButton}
      disabled={!!request.choices && chosen.length === 0}
      title={request.choices && chosen.length === 0
        ? request.multiple
          ? "Tick at least one option first"
          : "Choose one of the options first"
        : undefined}
      onclick={() => notificationState.settleConfirm(request.choices ? chosen : ["confirm"])}
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

  .choices {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    margin-top: var(--space-3);
  }

  .choice {
    display: flex;
    align-items: flex-start;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-3);
    background: var(--bg-tertiary);
    border-radius: var(--radius-sm);
    cursor: pointer;
  }

  .choice.unavailable {
    cursor: not-allowed;
    opacity: 0.6;
  }

  .choice input {
    margin-top: 3px;
  }

  .choice-text {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .choice-label {
    font-size: var(--text-sm);
    color: var(--text-primary);
  }

  .confirm-message {
    color: var(--text-secondary);
    font-size: var(--text-sm);
    line-height: 1.6;
    overflow-wrap: anywhere;
  }
</style>
