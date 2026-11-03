<script lang="ts">
  import type { Snippet } from "svelte";
  import type { HTMLButtonAttributes } from "svelte/elements";
  import { delayedFlag } from "../utils/delayedFlag.svelte";

  /**
   * A button for a request that takes a moment. It is disabled and busy for
   * as long as *pending* holds, so a second click can never send the request
   * twice; *pendingLabel* replaces the label only once the wait is noticeable.
   */
  let {
    pending = false,
    pendingLabel,
    disabled = false,
    type = "button",
    children,
    ...rest
  }: HTMLButtonAttributes & {
    pending?: boolean;
    pendingLabel?: string;
    children: Snippet;
  } = $props();

  const showPending = delayedFlag(() => pending);
</script>

<button {...rest} {type} disabled={disabled || pending} aria-busy={pending}>
  {#if showPending.current && pendingLabel}
    {pendingLabel}
  {:else}
    {@render children()}
  {/if}
</button>
